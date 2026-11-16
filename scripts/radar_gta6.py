
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
    for url in RSS_URLS:
        try:
            feed = feedparser.parse(url)

            for entry in feed.entries[:40]:
                title = clean(entry.get("title", ""))
                summary = clean(entry.get("summary", ""))
                text = (title + " " + summary).lower()

                if any(term.lower() in text for term in TERMS):
                    items.append({
                        "title": title,
                        "summary": summary[:800],
                        "url": entry.get("link", ""),
                        "published": entry.get("published", ""),
                        "source": url,
                    })

        except Exception as exc:
            print("RSS error:", url, exc)


def check_youtube(items):
    if not YOUTUBE_API_KEY:
        print("YouTube API: no hay API key configurada.")
        return

    if not should_check_youtube():
        print("YouTube API: todavía no toca consultar.")
        return

    print("Consultando YouTube...")

    # Registrar el intento para evitar repetir consultas
    # continuamente si la API devuelve un error.
    LAST_YOUTUBE_CHECK.write_text(
        json.dumps({"checked_at": now().isoformat()}, indent=2),
        encoding="utf-8",
    )

    try:
        params = {
            "part": "snippet",
            "q": "GTA 6",
            "type": "video",
            "order": "date",
            "maxResults": 10,
            "key": YOUTUBE_API_KEY,
        }

        response = requests.get(
            "https://www.googleapis.com/youtube/v3/search",
            params=params,
            timeout=20,
        )
        response.raise_for_status()

        for item in response.json().get("items", []):
            video_id = item.get("id", {}).get("videoId")
            snippet = item.get("snippet", {})

            if not video_id:
                continue

            items.append({
                "title": clean(snippet.get("title", "")),
                "summary": clean(snippet.get("description", ""))[:800],
                "url": "https://www.youtube.com/watch?v=" + video_id,
                "published": snippet.get("publishedAt", ""),
                "source": snippet.get("channelTitle", "YouTube"),
            })

    except Exception as exc:
        print("YouTube API error:", exc)


def main():
    DATA.mkdir(parents=True, exist_ok=True)

    seen = read(SEEN, {})
    items = []

    # Noticias: cada 15 minutos
    check_rss(items)

    # YouTube: como máximo una vez cada 60 minutos
    check_youtube(items)

    unique = {}

    for item in items:
        url = item.get("url")

        if url and url not in seen:
            unique[url] = item

    ranked = sorted(
        unique.values(),
        key=lambda item: item.get("published", ""),
        reverse=True,
    )

    candidates = {
        "checked_at": now().isoformat(),
        "items": ranked[:15],
    }

    CANDIDATES.write_text(
        json.dumps(candidates, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    timestamp = now().isoformat()

    for item in ranked:
        seen[item["url"]] = timestamp

    if len(seen) > 2500:
        seen = dict(list(seen.items())[-2000:])

    SEEN.write_text(
        json.dumps(seen, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("Temas nuevos:", len(ranked))
    print("Temas guardados:", min(len(ranked), 15))


if __name__ == "__main__":
    main()
