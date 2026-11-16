
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

DATA = ROOT / "data"
OUTPUT = ROOT / "output"

DATA.mkdir(parents=True, exist_ok=True)
OUTPUT.mkdir(parents=True, exist_ok=True)

YOUTUBE_API_KEY = os.getenv(
    "YOUTUBE_API_KEY", ""
).strip()

DEFAULT_RSS_URLS = [
    "https://www.ign.com/rss/v2/articles/feed",
    "https://feeds.feedburner.com/ign/games-all",
    "https://feeds.feedburner.com/ign/news",
    "https://www.pcgamer.com/feeds.xml",
    "https://www.rockpapershotgun.com/feed",
    "https://www.theverge.com/rss/games/index.xml",
]

# Si GitHub no proporciona NEWS_RSS_URLS,
# utilizar automáticamente las fuentes predeterminadas.
rss_environment = os.getenv("NEWS_RSS_URLS", "").strip()

if rss_environment:
    RSS_URLS = [
        url.strip()
        for url in rss_environment.split(",")
        if url.strip()
    ]
else:
    RSS_URLS = DEFAULT_RSS_URLS

print("RSS sources configured:", len(RSS_URLS))
