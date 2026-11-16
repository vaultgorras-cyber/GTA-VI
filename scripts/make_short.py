import os
import re
import json
import time
import math
import html
import asyncio
import subprocess
import urllib.request
import urllib.parse

from pathlib import Path
from datetime import datetime, timezone
from html.parser import HTMLParser

from PIL import Image, ImageDraw, ImageFont
import edge_tts

from config import DATA, OUTPUT


# ============================================================
# CONFIGURATION
# ============================================================

WIDTH = 1920
HEIGHT = 1080

MIN_AUDIO = 240
MAX_AUDIO = 420

MIN_WORDS = 600
MAX_WORDS = 850

MODEL = os.getenv(
    "OPENROUTER_MODEL",
    "nvidia/nemotron-3-ultra-550b-a55b:free"
)

OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
YOUTUBE_KEY = os.getenv("YOUTUBE_API_KEY", "").strip()

USER_AGENT = "GTA-VI-404-Automation/1.0"

FONT_PATH = (
    "/usr/share/fonts/truetype/dejavu/"
    "DejaVuSans-Bold.ttf"
)

# YouTube gameplay search phrases.
GAMEPLAY_SEARCHES = [
    "GTA 5 racing gameplay Creative Commons",
    "GTA 5 driving gameplay Creative Commons",
    "GTA 5 police chase gameplay Creative Commons",
    "GTA 6 gameplay Creative Commons",
    "Grand Theft Auto gameplay Creative Commons"
]


def log(*args):
    print("[GTA VI]", *args, flush=True)


def get_json(url, headers=None):

    h = {"User-Agent": USER_AGENT}

    if headers:
        h.update(headers)

    request = urllib.request.Request(url, headers=h)

    with urllib.request.urlopen(request, timeout=40) as response:
        return json.loads(response.read().decode("utf-8"))


# ============================================================
# NEWS SELECTION
# ============================================================

def load_news():

    path = DATA / "candidates.json"

    if not path.exists():
        return []

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("items", [])

    except Exception as error:
        log("News loading error:", error)
        return []


def choose_topic(items):

    if not items:
        return None

    def ranking(item):

        trend = (
            item.get("is_trending")
            or item.get("priority") == "trend"
        )

        score = int(
            item.get("trend_score", item.get("score", 0)) or 0
        )

        date = str(
            item.get("published", item.get("published_at", ""))
        )

        return int(bool(trend)), score, date

    return sorted(items, key=ranking, reverse=True)[0]


# ============================================================
# ARTICLE READING
# ============================================================

class ArticleParser(HTMLParser):

    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag.lower() in ("script", "style", "noscript"):
            self.skip += 1

    def handle_endtag(self, tag):
        if tag.lower() in ("script", "style", "noscript") and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            text = " ".join(data.split())
            if text:
                self.parts.append(text)


def read_article(url):

    if not url.startswith(("http://", "https://")):
        return ""

    try:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": USER_AGENT}
        )

        with urllib.request.urlopen(request, timeout=25) as response:
            raw = response.read(1000000).decode(
                "utf-8", errors="replace"
            )

        parser = ArticleParser()
        parser.feed(raw)

        return " ".join(parser.parts)[:9000]

    except Exception as error:
        log("Article unavailable:", error)
        return ""


# ============================================================
# AUTOMATIC SCRIPT
# ============================================================

def generate_script(item, article):

    if not OPENROUTER_KEY:
        raise RuntimeError("OPENROUTER_API_KEY is missing.")

    title = item.get("title", "GTA News")
    summary = item.get("summary", "")
    source = item.get("url", "")

    prompt = f"""
Write a professional YouTube narration in natural American English.

TOPIC:
{title}

SUMMARY:
{summary}

SOURCE:
{source}

ARTICLE:
{article}

REQUIREMENTS:
- 650 to 800 spoken words.
- Approximately five minutes.
- Strong but accurate opening.
- Explain the news and its importance to GTA players.
- GTA V, GTA VI, GTA IV and other GTA games may be discussed.
- Clearly distinguish confirmed information from rumours.
- Never invent facts, dates, quotes or announcements.
- Explain what is still unknown.
- Natural, engaging American English.
- No headings, bullets or markdown.
- Return only the spoken narration.
"""

    for attempt in range(1, 4):

        payload = {
            "model": MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a professional American gaming journalist. "
                        "Be accurate, engaging and never invent facts."
                    )
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "temperature": 0.4,
            "max_tokens": 6000
        }

        request = urllib.request.Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {OPENROUTER_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/",
                "X-Title": "GTAVI_404"
            }
        )

        try:

            with urllib.request.urlopen(request, timeout=180) as response:
                result = json.loads(response.read().decode("utf-8"))

            choice = result["choices"][0]
            script = choice["message"]["content"].strip()

            words = len(script.split())

            log("Script words:", words)

            if (
                MIN_WORDS <= words <= MAX_WORDS
                and choice.get("finish_reason") != "length"
            ):
                return script

        except Exception as error:
            log("OpenRouter error:", error)

        time.sleep(5)

    raise RuntimeError("Could not generate a complete narration.")


# ============================================================
# YOUTUBE GAMEPLAY SEARCH
# Only search videos declared Creative Commons by YouTube.
# ============================================================

def search_youtube_gameplay():

    if not YOUTUBE_KEY:
        raise RuntimeError("YOUTUBE_API_KEY is missing.")

    results = []
    seen = set()

    for phrase in GAMEPLAY_SEARCHES:

        params = {
            "part": "snippet",
            "type": "video",
            "q": phrase,
            "videoLicense": "creativeCommon",
            "maxResults": 10,
            "order": "relevance",
            "key": YOUTUBE_KEY
        }

        url = (
            "https://www.googleapis.com/youtube/v3/search?"
            + urllib.parse.urlencode(params)
        )

        try:
            data = get_json(url)

            for item in data.get("items", []):

                video_id = item.get(
                    "id", {}
                ).get("videoId")

                if not video_id or video_id in seen:
                    continue

                seen.add(video_id)

                snippet = item.get("snippet", {})

                results.append({
                    "id": video_id,
                    "title": snippet.get("title", ""),
                    "channel": snippet.get("channelTitle", ""),
                    "published": snippet.get("publishedAt", ""),
                    "url": f"https://www.youtube.com/watch?v={video_id}",
                    "license": "Creative Commons Attribution (YouTube API)"
                })

        except Exception as error:
            log("YouTube search error:", error)

    return results


def verify_youtube_license(video_id):

    params = {
        "part": "status,snippet",
        "id": video_id,
        "key": YOUTUBE_KEY
    }

    url = (
        "https://www.googleapis.com/youtube/v3/videos?"
        + urllib.parse.urlencode(params)
    )

    data = get_json(url)

    items = data.get("items", [])

    if not items:
        return False

    item = items[0]

    return (
        item.get("status", {}).get("license")
        == "creativeCommon"
    )


def download_gameplay(folder):

    folder.mkdir(parents=True, exist_ok=True)

    videos = search_youtube_gameplay()

    if not videos:
        raise RuntimeError(
            "No Creative Commons gameplay videos were found."
        )

    for video in videos:

        video_id = video["id"]

        try:

            if not verify_youtube_license(video_id):
                continue

            log("Checking gameplay:", video["title"])

            output = folder / "gameplay.%(ext)s"

            # yt-dlp is used only for videos returned as CC
            # and verified through the YouTube Data API.
            subprocess.run(
                [
                    "python",
                    "-m",
                    "yt_dlp",
                    "--no-playlist",
                    "--format",
                    "best[height<=1080][ext=mp4]/best[height<=1080]",
                    "--merge-output-format",
                    "mp4",
                    "--output",
                    str(output),
                    video["url"]
                ],
                check=True,
                timeout=300
            )

            matches = list(folder.glob("gameplay.*"))

            for path in matches:

                if path.suffix.lower() in (
                    ".mp4", ".mkv", ".webm", ".mov"
                ) and path.stat().st_size > 100000:

                    video["downloaded_file"] = str(path)

                    return path, video

        except Exception as error:
            log("Gameplay download failed:", error)

    raise RuntimeError(
        "No downloadable Creative Commons gameplay was available. "
        "Video cancelled."
    )


# ============================================================
# NEWS IMAGES
# Wikimedia Commons CC0 / CC BY / Public Domain
# ============================================================

def allowed_license(value):

    text = html.unescape(str(value or "")).lower()

    if re.search(r"\b(nc|nd)\b", text):
        return False

    if "noncommercial" in text or "no derivatives" in text:
        return False

    return any(term in text for term in (
        "public domain",
        "cc0",
        "cc by",
        "cc-by",
        "creative commons attribution"
    ))


def search_images(query):

    params = {
        "action": "query",
        "format": "json",
        "generator": "search",
        "gsrsearch": f"filetype:bitmap {query}",
        "gsrnamespace": 6,
        "gsrlimit": 20,
        "prop": "imageinfo",
        "iiprop": "url|extmetadata",
        "iiurlwidth": 1920
    }

    url = (
        "https://commons.wikimedia.org/w/api.php?"
        + urllib.parse.urlencode(params)
    )

    data = get_json(url)

    assets = []

    pages = data.get(
        "query", {}
    ).get(
        "pages", {}
    )

    for page in pages.values():

        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata", {})

        license_name = meta.get(
            "LicenseShortName", {}
        ).get("value", "")

        usage = meta.get(
            "UsageTerms", {}
        ).get("value", "")

        if not (
            allowed_license(license_name)
            or allowed_license(usage)
        ):
            continue

        image_url = info.get("thumburl") or info.get("url")

        if not image_url:
            continue

        assets.append({
            "url": image_url,
            "title": page.get("title", ""),
            "source": info.get("descriptionurl", ""),
            "license": license_name or usage,
            "author": meta.get("Artist", {}).get(
                "value", "Unknown"
            )
        })

    return assets


def download_news_images(title, folder):

    folder.mkdir(parents=True, exist_ok=True)

    queries = [
        title,
        "Grand Theft Auto VI",
        "Grand Theft Auto V",
        "Vice City Miami",
        "Miami skyline"
    ]

    found = []
    seen = set()

    for query in queries:

        try:

            for asset in search_images(query):

                if asset["url"] in seen:
                    continue

                seen.add(asset["url"])
                found.append(asset)

        except Exception as error:
            log("Image search error:", error)

    downloaded = []

    for index, asset in enumerate(found[:20]):

        try:

            request = urllib.request.Request(
                asset["url"],
                headers={"User-Agent": USER_AGENT}
            )

            with urllib.request.urlopen(request, timeout=40) as response:
                content = response.read()

            path = folder / f"news_{index:02d}.jpg"
            path.write_bytes(content)

            with Image.open(path) as image:
                image.verify()

            asset["path"] = str(path)
            downloaded.append(asset)

        except Exception as error:
            log("Image download failed:", error)

    return downloaded


# ============================================================
# NATURAL VOICE
# ============================================================

async def generate_voice(script, output):

    voices = [
        "en-US-ChristopherNeural",
        "en-US-GuyNeural",
        "en-US-AriaNeural"
    ]

    for voice in voices:

        try:

            if output.exists():
                output.unlink()

            await edge_tts.Communicate(
                script,
                voice,
                rate="-4%"
            ).save(str(output))

            if output.exists() and output.stat().st_size > 5000:
                log("Voice generated:", voice)
                return output

        except Exception as error:
            log("Voice failed:", voice, error)
            await asyncio.sleep(2)

    raise RuntimeError("Natural voice generation failed.")


def get_audio_duration(path):

    result = subprocess.run(
        [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path)
        ],
        capture_output=True,
        text=True,
        check=True
    )

    return float(result.stdout.strip())


# ============================================================
# NEWS IMAGE OVERLAYS
# ============================================================

def make_news_card(image_path, output):

    with Image.open(image_path) as source:
        image = source.convert("RGB")

    image.thumbnail((760, 430), Image.Resampling.LANCZOS)

    canvas = Image.new(
        "RGB",
        (800, 470),
        (12, 12, 18)
    )

    x = (800 - image.width) // 2
    y = (470 - image.height) // 2

    canvas.paste(image, (x, y))

    draw = ImageDraw.Draw(canvas)

    draw.rectangle(
        (0, 0, 799, 469),
        outline=(255, 255, 255),
        width=5
    )

    canvas.save(output, quality=92)


def make_subtitle_file(script, duration, path):

    words = script.split()

    chunks = [
        words[i:i + 10]
        for i in range(0, len(words), 10)
    ]

    total = len(words)
    current = 0.0
    blocks = []

    def stamp(seconds):

        ms = int(seconds * 1000)

        h, ms = divmod(ms, 3600000)
        m, ms = divmod(ms, 60000)
        s, ms = divmod(ms, 1000)

        return f"{h:02}:{m:02}:{s:02},{ms:03}"

    for index, chunk in enumerate(chunks, 1):

        span = duration * len(chunk) / total
        end = min(duration, current + span)

        blocks.append(
            f"{index}\n"
            f"{stamp(current)} --> {stamp(end)}\n"
            f"{' '.join(chunk)}\n"
        )

        current = end

    path.write_text("\n".join(blocks), encoding="utf-8")


# ============================================================
# FINAL VIDEO: GAMEPLAY BACKGROUND + NEWS IMAGE OVERLAYS
# ============================================================

def create_video(
    title,
    script,
    gameplay,
    audio,
    duration,
    stamp,
    news_images
):

    if not news_images:
        raise RuntimeError(
            "No news images found. Video cancelled."
        )

    work = OUTPUT / f"work_{stamp}"
    work.mkdir(parents=True, exist_ok=True)

    cards = []

    for index, asset in enumerate(news_images):

        card = work / f"card_{index:03d}.jpg"

        make_news_card(
            asset["path"],
            card
        )

        cards.append(card)

    # Create a timed slideshow of news photographs.
    card_duration = max(8, duration / len(cards))

    concat = work / "cards.txt"

    with concat.open("w", encoding="utf-8") as file:

        for card in cards:

            file.write(f"file '{card.resolve()}'\n")
            file.write(f"duration {card_duration:.3f}\n")

        file.write(f"file '{cards[-1].resolve()}'\n")

    slideshow = work / "news_slideshow.mp4"

    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat),
            "-vf",
            "fps=25,scale=800:470,format=yuv420p",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-pix_fmt", "yuv420p",
            "-t", str(duration),
            str(slideshow)
        ],
        check=True
    )

    subtitles = OUTPUT / f"gta_vi_{stamp}.srt"

    make_subtitle_file(
        script,
        duration,
        subtitles
    )

    video = OUTPUT / f"gta_vi_{stamp}.mp4"

    subtitle_filter = (
        str(subtitles.resolve())
        .replace("\\", "/")
        .replace(":", "\\:")
    )

    # Gameplay fills the screen.
    # News photographs appear as a large inset panel.
    filter_complex = (
        "[0:v]scale=1920:1080:force_original_aspect_ratio=increase,"
        "crop=1920:1080[bg];"
        "[1:v]scale=800:470[news];"
        "[bg][news]overlay=1050:100:shortest=0,"
        "format=yuv420p,"
        f"subtitles='{subtitle_filter}'[outv]"
    )

    subprocess.run(
        [
            "ffmpeg", "-y",
            "-stream_loop", "-1",
            "-i", str(gameplay),
            "-i", str(slideshow),
            "-i", str(audio),
            "-filter_complex", filter_complex,
            "-map", "[outv]",
            "-map", "2:a",
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "21",
            "-c:a", "aac",
            "-b:a", "192k",
            "-t", str(duration),
            "-shortest",
            "-movflags", "+faststart",
            str(video)
        ],
        check=True
    )

    return video, subtitles


# ============================================================
# MAIN
# ============================================================

def main():

    OUTPUT.mkdir(parents=True, exist_ok=True)

    items = load_news()
    item = choose_topic(items)

    if not item:
        log("No pending GTA topic.")
        return

    title = str(item.get("title", "GTA News"))
    source = str(item.get("url", ""))

    stamp = datetime.now(
        timezone.utc
    ).strftime("%Y%m%d_%H%M%S")

    log("Selected topic:", title)

    article = read_article(source)

    script = generate_script(
        item,
        article
    )

    words = len(script.split())

    log("Narration generated:", words, "words")

    work = OUTPUT / f"assets_{stamp}"
    work.mkdir(parents=True, exist_ok=True)

    # Search and download reusable gameplay.
    gameplay, gameplay_info = download_gameplay(
        work / "gameplay"
    )

    # Search and download images related to the news.
    news_images = download_news_images(
        title,
        work / "news"
    )

    audio = OUTPUT / f"voice_{stamp}.mp3"

    audio = asyncio.run(
        generate_voice(script, audio)
    )

    duration = get_audio_duration(audio)

    log("Narration duration:", round(duration, 1))

    if not MIN_AUDIO <= duration <= MAX_AUDIO:
        raise RuntimeError(
            "Narration is outside the required duration."
        )

    video, subtitles = create_video(
        title,
        script,
        gameplay,
        audio,
        duration,
        stamp,
        news_images
    )

    report = {
        "title": title,
        "source": source,
        "model": MODEL,
        "word_count": words,
        "duration": duration,
        "video": str(video),
        "subtitles": str(subtitles),
        "gameplay": gameplay_info,
        "news_images": [
            {
                "title": x.get("title"),
                "source": x.get("source"),
                "license": x.get("license"),
                "author": x.get("author")
            }
            for x in news_images
        ],
        "script": script
    }

    report_path = OUTPUT / f"gta_vi_{stamp}_report.json"

    report_path.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    log("VIDEO SUCCESSFULLY GENERATED:", video)
    log("REPORT:", report_path)


if __name__ == "__main__":
    main()
