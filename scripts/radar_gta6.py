
import json
import re
import hashlib
import unicodedata
from datetime import datetime, timezone, timedelta

import feedparser
import requests

from config import DATA, RSS_URLS, YOUTUBE_API_KEY


SEEN = DATA / "seen.json"
CANDIDATES = DATA / "candidates.json"
LAST_YOUTUBE_CHECK = DATA / "last_youtube_check.json"

YOUTUBE_INTERVAL_MINUTES = 15
MAX_CANDIDATES = 100

GTA_PATTERN = re.compile(
    r"\b(?:GTA\s*(?:VI|6)|Grand Theft Auto\s*(?:VI|6))\b",
    re.IGNORECASE,
)

ROCKSTAR_PATTERN = re.compile(
    r"\bRockstar Games\b",
    re.IGNORECASE,
)

SPAM_PATTERNS = [
    r"\bfree giveaway\b",
    r"\bfree money\b",
    r"\bsubscribe to win\b",
    r"\bget rich quick\b",
    r"\bdownload now\b",
    r"\bcheat download\b",
    r"\bmod menu download\b",
]

BLOCKED_TERMS = [
    "gta 5",
    "gta v",
    "grand theft auto v",
    "gta online",
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


def is_mostly_latin(text):
    letters = [
        char for char in text
        if unicodedata.category(char).startswith("L")
    ]

    if not letters:
        return False

    latin = sum(
        1 for char in letters
        if "LATIN" in unicodedata.name(char, "")
    )

    return latin / len(letters) >= 0.85


def is_spam(title, summary):
    text = (title + " " + summary).lower()

    return any(
        re.search(pattern, text, re.IGNORECASE)
        for pattern in SPAM_PATTERNS
    )


def is_relevant(title, summary):
    title = clean(title)
    summary = clean(summary)

    if not title:
        return False

    # Reject titles written mainly in non-Latin scripts.
    if not is_mostly_latin(title):
        print("Rejected non-Latin title:", title[:120])
        return False

    # Reject obvious GTA V / GTA Online content.
    title_lower = title.lower()

    if any(term in title_lower for term in BLOCKED_TERMS):
        return False

    # GTA VI must be explicitly present in the title.
    # Rockstar alone is not enough.
    if not GTA_PATTERN.search(title):
        return False

    if is_spam(title, summary):
        print("Rejected spam-like topic:", title[:120])
        return False

    return True


def parse_date(value):
    if not value:
        return None

    try:
        result = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )

        if result.tzinfo is None:
            result = result.replace(tzinfo=timezone.utc)

        return result.astimezone(timezone.utc)

    except Exception:
        return None


def should_check_youtube():
    data = read(LAST_YOUTUBE_CHECK, {})
    previous = parse_date(data.get("checked_at", ""))

    if not previous:
        return True

    return now() - previous >= timedelta(
        minutes=YOUTUBE_INTERVAL_MINUTES
    )


def check_rss(items):
    print("Checking RSS sources...")

    for url in RSS_URLS:
        try:
            feed = feedparser.parse(url)
            count = 0

            if getattr(feed, "bozo", False):
                print("RSS warning:", url, feed.bozo_exception)

            for entry in feed.entries[:50]:
                title = clean(entry.get("title", ""))
                summary = clean(entry.get("summary", ""))
                link = entry.get("link", "")

                if not link:
                    continue

                if not is_relevant(title, summary):
                    continue

                items.append({
                    "title": title,
                    "summary": summary[:2500],
                    "url": link,
                    "published": (
                        entry.get("published", "")
                        or entry.get("updated", "")
                    ),
                    "source": url,
                    "source_type": "rss",
                })

                count += 1

            print("RSS articles accepted:", url, count)

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
        response = requests.get(
            "https://www.googleapis.com/youtube/v3/search",
            params={
                "part": "snippet",
                "q": "GTA VI OR GTA 6",
                "type": "video",
                "order": "date",
                "publishedAfter": (
                    now() - timedelta(days=7)
                ).isoformat(),
                "maxResults": 25,
                "key": YOUTUBE_API_KEY,
            },
            timeout=30,
        )

        response.raise_for_status()
        results = response.json()

        video_ids = []

        for result in results.get("items", []):
            video_id = result.get("id", {}).get("videoId")
            snippet = result.get("snippet", {})

            if not video_id:
                continue

            title = clean(snippet.get("title", ""))
            summary = clean(snippet.get("description", ""))

            if not is_relevant(title, summary):
                continue

            video_ids.append(video_id)

            items.append({
                "title": title,
                "summary": summary[:2500],
                "url": "https://www.youtube.com/watch?v=" + video_id,
                "published": snippet.get("publishedAt", ""),
                "source": snippet.get("channelTitle", "YouTube"),
                "source_type": "youtube",
                "youtube_video_id": video_id,
            })

        if video_ids:
            stats_response = requests.get(
                "https://www.googleapis.com/youtube/v3/videos",
                params={
                    "part": "statistics",
                    "id": ",".join(video_ids),
                    "key": YOUTUBE_API_KEY,
                },
                timeout=30,
            )

            stats_response.raise_for_status()

            stats = {
                video["id"]: video.get("statistics", {})
                for video in stats_response.json().get("items", [])
            }

            for item in items:
                video_id = item.get("youtube_video_id")

                if video_id in stats:
                    item["views"] = int(
                        stats[video_id].get("viewCount", 0)
                    )

        LAST_YOUTUBE_CHECK.write_text(
            json.dumps(
                {"checked_at": now().isoformat()},
                indent=2,
            ),
            encoding="utf-8",
        )

        print("YouTube videos accepted:", len(video_ids))

    except Exception as exc:
        print("YouTube API error:", str(exc))


def topic_key(item):
    title = clean(item.get("title", "")).lower()
    title = re.sub(r"[^a-z0-9 ]", " ", title)
    title = re.sub(r"\s+", " ", title).strip()

    return hashlib.sha1(
        title.encode("utf-8")
    ).hexdigest()


def score_item(item, all_items):
    published = parse_date(item.get("published", ""))
    age_hours = 999

    if published:
        age_hours = max(
            0,
            (now() - published).total_seconds() / 3600
        )

    if age_hours <= 6:
        recency_score = 40
    elif age_hours <= 24:
        recency_score = 30
    elif age_hours <= 48:
        recency_score = 20
    elif age_hours <= 168:
        recency_score = 10
    else:
        recency_score = 0

    key = topic_key(item)

    matching = [
        other for other in all_items
        if topic_key(other) == key
    ]

    distinct_sources = {
        other.get("source", "")
        for other in matching
        if other.get("source")
    }

    source_score = min(
        30,
        len(distinct_sources) * 10
    )

    views = max(
        [int(other.get("views", 0)) for other in matching]
        or [0]
    )

    if views >= 1_000_000:
        views_score = 20
    elif views >= 100_000:
        views_score = 15
    elif views >= 10_000:
        views_score = 10
    elif views >= 1_000:
        views_score = 5
    else:
        views_score = 0

    score = recency_score + source_score + views_score

    trending = (
        score >= 60
        and age_hours <= 48
        and (
            len(distinct_sources) >= 2
            or views >= 100_000
        )
    )

    item["trend_score"] = score
    item["is_trending"] = trending
    item["priority"] = (
        "trend" if trending else "regular"
    )
    item["topic_id"] = key

    return item


def main():
    DATA.mkdir(parents=True, exist_ok=True)

    seen = read(SEEN, {})

    if not isinstance(seen, dict):
        seen = {}

    old_candidates = read(CANDIDATES, {})
    pending = old_candidates.get("items", [])

    found = []

    # Keep only valid pending topics.
    for item in pending:
        title = clean(item.get("title", ""))
        summary = clean(item.get("summary", ""))
        url = item.get("url", "")

        if not url or url in seen:
            continue

        if is_relevant(title, summary):
            found.append(item)

    print("================================")
    print("GTA VI QUALITY RADAR")
    print("================================")

    check_rss(found)
    check_youtube(found)

    unique = {}

    for item in found:
        url = item.get("url", "")

        if not url or url in seen:
            continue

        unique[url] = item

    all_items = list(unique.values())

    ranked = [
        score_item(item, all_items)
        for item in all_items
    ]

    ranked.sort(
        key=lambda item: (
            item.get("is_trending", False),
            item.get("trend_score", 0),
            parse_date(item.get("published", ""))
            or datetime.min.replace(tzinfo=timezone.utc),
        ),
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

    trends = sum(
        1 for item in selected
        if item.get("is_trending")
    )

    print("Pending valid topics:", len(selected))
    print("Potential trends:", trends)
    print("Rejected or removed old invalid topics:",
          len(pending) - sum(
              1 for item in pending
              if item.get("url") not in seen
              and is_relevant(
                  clean(item.get("title", "")),
                  clean(item.get("summary", ""))
              )
          ))

    if selected:
        print("Next priority:", selected[0]["priority"])
        print("Next score:", selected[0]["trend_score"])
        print("Next topic:", selected[0]["title"])

    print("Radar check completed.")


if __name__ == "__main__":
    main()
