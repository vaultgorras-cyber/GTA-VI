
import json
import re
import hashlib
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

import feedparser
import requests

from config import DATA, RSS_URLS, YOUTUBE_API_KEY


SEEN = DATA / "seen.json"
CANDIDATES = DATA / "candidates.json"
LAST_YOUTUBE_CHECK = DATA / "last_youtube_check.json"

YOUTUBE_INTERVAL_MINUTES = 15
MAX_CANDIDATES = 100

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


def parse_date(value):
    if not value:
        return None

    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            result = result.replace(tzinfo=timezone.utc)
        return result.astimezone(timezone.utc)
    except Exception:
        pass

    try:
        result = parsedate_to_datetime(value)
        if result.tzinfo is None:
            result = result.replace(tzinfo=timezone.utc)
        return result.astimezone(timezone.utc)
    except Exception:
        return None


def is_relevant(title, summary):
    text = (title + " " + summary).lower()
    return any(term.lower() in text for term in TERMS)


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

                if not link or not is_relevant(title, summary):
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
            "publishedAfter": (
                now() - timedelta(days=7)
            ).isoformat(),
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

        print("YouTube videos found:", len(video_ids))

    except Exception as exc:
        print("YouTube API error:", str(exc))


def topic_key(item):
    title = clean(item.get("title", "")).lower()
    title = re.sub(r"[^a-z0-9 ]", " ", title)
    title = re.sub(r"\s+", " ", title).strip()

    # Stable identifier based on the normalized title.
    return hashlib.sha1(title.encode("utf-8")).hexdigest()


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

    # Count distinct sources reporting the same normalized title.
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

    source_score = min(30, len(distinct_sources) * 10)

    youtube_views = max(
        [int(other.get("views", 0)) for other in matching] or [0]
    )

    if youtube_views >= 1_000_000:
        views_score = 20
    elif youtube_views >= 100_000:
        views_score = 15
    elif youtube_views >= 10_000:
        views_score = 10
    elif youtube_views >= 1_000:
        views_score = 5
    else:
        views_score = 0

    score = recency_score + source_score + views_score

    # A provisional signal, not a claim of measured search trends.
    is_trending = (
        score >= 60
        and age_hours <= 48
        and (
            len(distinct_sources) >= 2
            or youtube_views >= 100_000
        )
    )

    item["trend_score"] = score
    item["is_trending"] = is_trending
    item["priority"] = "trend" if is_trending else "regular"
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

    # Keep pending items that have not been completed.
    for item in pending:
        if item.get("url") and item["url"] not in seen:
            found.append(item)

    print("================================")
    print("GTA VI RADAR")
    print("================================")

    check_rss(found)
    check_youtube(found)

    # Remove duplicate URLs without losing pending topics.
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

    print("Pending topics:", len(selected))
    print("Potential trend topics:", trends)

    if selected:
        print("Next priority:", selected[0].get("priority"))
        print("Next score:", selected[0].get("trend_score"))
        print("Next topic:", selected[0].get("title", ""))

    print("Radar check completed.")


if __name__ == "__main__":
    main()
