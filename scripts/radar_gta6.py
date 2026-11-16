
import json
import re
from datetime import datetime, timezone, timedelta

import feedparser
import requests

from config import DATA, RSS_URLS, YOUTUBE_API_KEY


SEEN = DATA / "seen.json"
CANDIDATES = DATA / "candidates.json"
LAST_YOUTUBE_CHECK = DATA / "last_youtube_check.json"

YOUTUBE_INTERVAL_MINUTES = 60
MAX_CANDIDATES = 50

TERMS = [
    "GTA 6",
    "GTA VI",
    "Grand Theft Auto VI",
    "Vice City",
    "Lucia",
    "Jason",
    "Rockstar Games",
]


def now():
    return datetime.now(timezone.utc)


def read(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def is_relevant(title, summary):
    text = (title + " " + summary).lower()
    return any(term.lower() in text for term in TERMS)


def published_key(item):
    return item.get("published", "") or ""


def should_check_youtube():
    data = read(LAST_YOUTUBE_CHECK, {})
    last_check = data.get("checked_at")

    if not last_check:
        return True

    try:
        previous = datetime.fromisoformat(last_check)

        if previous.tzinfo is None:
            previous = previous.replace(tzinfo=timezone.utc)

        return now() - previous >= timedelta(
            minutes=YOUTUBE_INTERVAL_MINUTES
        )

    except Exception:
        return True


def check_rss(items):
    print("Checking RSS sources...")

    for url in RSS_URLS:
        try:
            feed = feedparser.parse(url)

            if getattr(feed, "bozo", False):
                print("RSS warning:", url, feed.bozo_exception)

            count = 0

            for entry in feed.entries[:50]:
                title = clean(entry.get("title", ""))
                summary = clean(entry.get("summary", ""))
                link = entry.get("link", "")

                if not link or not is_relevant(title, summary):
                    continue

                items.append({
                    "title": title,
                    "summary": summary[:1500],
                    "url": link,
                    "published": entry.get("published", ""),
                    "source": url,
                })

                count += 1

            print("RSS articles found:", url, count)

        except Exception as exc:
            print("RSS error:", url, str(exc))


def check_youtube(items):
    if not YOUTUBE_API_KEY:
        print("YouTube API: missing API key.")
        return

    if not should_check_youtube():
        print("YouTube API: next check is not due yet.")
        return

    print("Checking YouTube...")

    try:
        params = {
            "part": "snippet",
            "q": "GTA VI OR GTA 6",
            "type": "video",
            "order": "date",
            "maxResults": 25,
            "key": YOUTUBE_API_KEY,
        }

        response = requests.get(
            "https://www.googleapis.com/youtube/v3/search",
            params=params,
            timeout=30,
        )

        response.raise_for_status()
        results = response.json()

        for result in results.get("items", []):
            video_id = result.get("id", {}).get("videoId")
            snippet = result.get("snippet", {})

            if not video_id:
                continue

            title = clean(snippet.get("title", ""))
            summary = clean(snippet.get("description", ""))

            if not is_relevant(title, summary):
                continue

            items.append({
                "title": title,
                "summary": summary[:1500],
                "url": "https://www.youtube.com/watch?v=" + video_id,
                "published": snippet.get("publishedAt", ""),
                "source": snippet.get("channelTitle", "YouTube"),
            })

        LAST_YOUTUBE_CHECK.write_text(
            json.dumps(
                {"checked_at": now().isoformat()},
                indent=2
            ),
            encoding="utf-8",
        )

        print(
            "YouTube videos found:",
            len(results.get("items", []))
        )

    except Exception as exc:
        print("YouTube API error:", str(exc))


def main():
    DATA.mkdir(parents=True, exist_ok=True)

    seen = read(SEEN, {})
    old_candidates = read(CANDIDATES, {})
    pending = old_candidates.get("items", [])

    found = []

    # Keep existing pending stories.
    for item in pending:
        if item.get("url"):
            found.append(item)

    # Collect new RSS and YouTube stories.
    check_rss(found)
    check_youtube(found)

    unique = {}

    for item in found:
        url = item.get("url")

        if not url:
            continue

        if url in seen:
            continue

        unique[url] = item

    ranked = sorted(
        unique.values(),
        key=published_key,
        reverse=True,
    )

    selected = ranked[:MAX_CANDIDATES]

    CANDIDATES.write_text(
        json.dumps(
            {
                "checked_at": now().isoformat(),
                "items": selected,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("New topics available:", len(selected))
    print("Total pending candidates:", len(selected))

    if selected:
        print("Next topic:", selected[0].get("title", ""))


if __name__ == "__main__":
    main()
