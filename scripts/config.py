import os
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
DATA, OUTPUT = ROOT/"data", ROOT/"output"
DATA.mkdir(exist_ok=True); OUTPUT.mkdir(exist_ok=True)
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "").strip()
RSS_URLS = [x.strip() for x in os.getenv("NEWS_RSS_URLS", "https://www.rockstargames.com/newswire,https://feeds.feedburner.com/ign/all").split(",") if x.strip()]
