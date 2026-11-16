import os
import re
import json
import html
import time
import math
import asyncio
import subprocess
import urllib.request
import urllib.parse
import urllib.error
from pathlib import Path
from datetime import datetime, timezone
from html.parser import HTMLParser

from PIL import Image, ImageDraw, ImageFont
import edge_tts

from config import DATA, OUTPUT

# ==================================================
# GTA VI AUTOMATIC VIDEO GENERATOR
# ==================================================

WIDTH = 1920
HEIGHT = 1080

MIN_AUDIO = 240
MAX_AUDIO = 420
MIN_WORDS = 600
MAX_WORDS = 850

SCENE_SECONDS = 12
MAX_ATTEMPTS = 3

MODEL = os.getenv(
    "OPENROUTER_MODEL",
    "nvidia/nemotron-3-ultra-550b-a55b:free"
)

API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()

HEADERS = {
    "User-Agent": "GTA-VI-Automation/1.0"
}

FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"
]


def log(message):
    print("[GTA VI]", message, flush=True)


def get_json(url, headers=None):
    h = dict(HEADERS)
    if headers:
        h.update(headers)

    req = urllib.request.Request(url, headers=h)

    with urllib.request.urlopen(req, timeout=40) as response:
        return json.loads(response.read().decode("utf-8"))


def load_news():
    path = DATA / "candidates.json"

    if not path.exists():
        return []

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("items", [])
    except Exception as error:
        log(error)
        return []


def choose_topic(items):
    if not items:
        return None

    def ranking(item):
        trending = (
            item.get("is_trending")
            or item.get("priority") == "trend"
        )

        score = int(
            item.get("trend_score", item.get("score", 0)) or 0
        )

        date = str(
            item.get("published", item.get("published_at", ""))
        )

        return (int(bool(trending)), score, date)

    return sorted(items, key=ranking, reverse=True)[0]


# ==================================================
# READ SOURCE ARTICLE
# ==================================================

class ArticleParser(HTMLParser):

    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self.skip:
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
        req = urllib.request.Request(
            url,
            headers=HEADERS
        )

        with urllib.request.urlopen(req, timeout=25) as response:
            raw = response.read(1000000).decode(
                "utf-8",
                errors="replace"
            )

        parser = ArticleParser()
        parser.feed(raw)

        return " ".join(parser.parts)[:8000]

    except Exception as error:
        log("Article unavailable:", error)
        return ""


# ==================================================
# AUTOMATIC SCRIPT GENERATION
# ==================================================

def generate_script(item, article):

    if not API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY missing.")

    title = item.get("title", "GTA News")
    summary = item.get("summary", "")
    url = item.get("url", "")

    prompt = f"""
Create a professional YouTube GTA news narration.

TOPIC:
{title}

SUMMARY:
{summary}

SOURCE:
{url}

ARTICLE:
{article}

REQUIREMENTS:

- Write 650 to 800 spoken words.
- Natural American English.
- Approximately five minutes.
- Strong opening hook.
- Explain the story clearly.
- Include relevant GTA history and comparisons.
- GTA V, GTA VI, GTA IV and other GTA games may be mentioned.
- Separate confirmed facts from rumours.
- Never invent information.
- Explain why the news matters to players.
- End with a strong conclusion.
- No headings, markdown or bullet points.
- Return narration only.
"""

    for attempt in range(MAX_ATTEMPTS):

        payload = {
            "model": MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a professional American gaming journalist. "
                        "Write accurate, engaging YouTube narrations."
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
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/",
                "X-Title": "GTA VI Automation"
            }
        )

        try:
            with urllib.request.urlopen(
                request,
                timeout=180
            ) as response:
                result = json.loads(
                    response.read().decode("utf-8")
                )

            choice = result["choices"][0]
            script = choice["message"]["content"].strip()

            words = len(script.split())

            log("Generated words:", words)

            if (
                MIN_WORDS <= words <= MAX_WORDS
                and choice.get("finish_reason") != "length"
            ):
                return script

        except Exception as error:
            log("OpenRouter error:", error)

        time.sleep(5)

    raise RuntimeError("Could not generate a complete script.")


# ==================================================
# VISUAL SEARCH - WIKIMEDIA COMMONS
# ==================================================

def acceptable_license(value):

    text = html.unescape(str(value)).lower()

    if "noncommercial" in text or "no derivatives" in text:
        return False

    if re.search(r"\b(nc|nd)\b", text):
        return False

    return any(x in text for x in (
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

    pages = data.get("query", {}).get("pages", {})

    for page in pages.values():

        info = (page.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata", {})

        license_name = meta.get(
            "LicenseShortName", {}
        ).get("value", "")

        if not acceptable_license(license_name):
            continue

        image_url = info.get("thumburl") or info.get("url")

        if not image_url:
            continue

        assets.append({
            "url": image_url,
            "title": page.get("title", ""),
            "source": info.get("descriptionurl", ""),
            "license": license_name,
            "author": meta.get("Artist", {}).get(
                "value", "Unknown"
            )
        })

    return assets


def download_visuals(title, folder):

    folder.mkdir(parents=True, exist_ok=True)

    queries = [
        title,
        "Grand Theft Auto VI",
        "Grand Theft Auto V",
        "Vice City Miami",
        "Miami city skyline",
        "Florida sports cars"
    ]

    assets = []
    seen = set()

    for query in queries:

        try:
            results = search_images(query)

            for asset in results:

                if asset["url"] in seen:
                    continue

                seen.add(asset["url"])
                assets.append(asset)

        except Exception as error:
            log("Image search error:", error)

        if len(assets) >= 20:
            break

    downloaded = []

    for index, asset in enumerate(assets[:20]):

        try:
            req = urllib.request.Request(
                asset["url"],
                headers=HEADERS
            )

            with urllib.request.urlopen(req, timeout=40) as response:
                content = response.read()

            path = folder / f"image_{index:02d}.jpg"
            path.write_bytes(content)

            with Image.open(path) as image:
                image.verify()

            asset["path"] = str(path)
            downloaded.append(asset)

        except Exception as error:
            log("Image download error:", error)

    log("Usable images:", len(downloaded))

    return downloaded


# ==================================================
# NATURAL ENGLISH VOICE
# ==================================================

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
                log("Voice:", voice)
                return output

        except Exception as error:
            log("Voice error:", error)

            await asyncio.sleep(2)

    raise RuntimeError(
        "Natural voice generation failed. Video cancelled."
    )


def audio_duration(path):

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


# ==================================================
# VIDEO GRAPHICS
# ==================================================

def get_font(size):

    for path in FONT_PATHS:

        if Path(path).exists():
            return ImageFont.truetype(path, size)

    return ImageFont.load_default()


def make_scene(image_path, title, number, output):

    with Image.open(image_path) as original:
        image = original.convert("RGB")

    scale = max(
        WIDTH / image.width,
        HEIGHT / image.height
    )

    image = image.resize((
        int(image.width * scale),
        int(image.height * scale)
    ))

    x = (image.width - WIDTH) // 2
    y = (image.height - HEIGHT) // 2

    image = image.crop((
        x, y, x + WIDTH, y + HEIGHT
    ))

    overlay = Image.new(
        "RGBA",
        (WIDTH, HEIGHT),
        (0, 0, 0, 100)
    )

    image = Image.alpha_composite(
        image.convert("RGBA"),
        overlay
    )

    draw = ImageDraw.Draw(image)

    draw.text(
        (90, 80),
        "GTA NEWS & ANALYSIS",
        font=get_font(38),
        fill="white"
    )

    title_font = get_font(48)

    words = title.upper().split()
    lines = []
    current = ""

    for word in words:

        test = (current + " " + word).strip()

        if draw.textbbox(
            (0, 0),
            test,
            font=title_font
        )[2] < 1500:
            current = test
        else:
            lines.append(current)
            current = word

    if current:
        lines.append(current)

    y = 820

    for line in lines[:2]:

        draw.text(
            (90, y),
            line,
            font=title_font,
            fill="white",
            stroke_width=3,
            stroke_fill="black"
        )

        y += 65

    draw.text(
        (1780, 980),
        str(number),
        font=get_font(30),
        fill="white"
    )

    image.convert("RGB").save(output, quality=92)


# ==================================================
# SUBTITLES
# ==================================================

def srt_time(seconds):

    milliseconds = int(seconds * 1000)

    hours, milliseconds = divmod(milliseconds, 3600000)
    minutes, milliseconds = divmod(milliseconds, 60000)
    seconds, milliseconds = divmod(milliseconds, 1000)

    return (
        f"{hours:02}:"
        f"{minutes:02}:"
        f"{seconds:02},"
        f"{milliseconds:03}"
    )


def create_subtitles(script, duration, path):

    words = script.split()

    chunks = [
        words[i:i + 10]
        for i in range(0, len(words), 10)
    ]

    total = len(words)
    current = 0
    blocks = []

    for number, chunk in enumerate(chunks, 1):

        span = duration * len(chunk) / total
        end = current + span

        blocks.append(
            f"{number}\n"
            f"{srt_time(current)} --> {srt_time(end)}\n"
            f"{' '.join(chunk)}\n"
        )

        current = end

    path.write_text(
        "\n".join(blocks),
        encoding="utf-8"
    )


# ==================================================
# VIDEO EDITING
# ==================================================

def create_video(title, script, audio, duration, stamp, assets):

    if not assets:
        raise RuntimeError(
            "No reusable licensed images found. Video cancelled."
        )

    work = OUTPUT / f"work_{stamp}"
    work.mkdir(parents=True, exist_ok=True)

    scenes = []

    count = math.ceil(duration / SCENE_SECONDS)

    for index in range(count):

        asset = assets[index % len(assets)]

        scene = work / f"scene_{index:03d}.jpg"

        make_scene(
            asset["path"],
            title,
            index + 1,
            scene
        )

        scenes.append(scene)

    concat = work / "concat.txt"

    with concat.open("w", encoding="utf-8") as file:

        for index, scene in enumerate(scenes):

            seconds = min(
                SCENE_SECONDS,
                duration - index * SCENE_SECONDS
            )

            file.write(f"file '{scene.resolve()}'\n")
            file.write(f"duration {seconds:.3f}\n")

        file.write(f"file '{scenes[-1].resolve()}'\n")

    subtitles = OUTPUT / f"gta_vi_{stamp}.srt"

    create_subtitles(
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

    filters = (
        "fps=25,"
        "scale=1920:1080:force_original_aspect_ratio=decrease,"
        "pad=1920:1080:(ow-iw)/2:(oh-ih)/2,"
        "format=yuv420p,"
        f"subtitles='{subtitle_filter}'"
    )

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat),
            "-i", str(audio),
            "-vf", filters,
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


# ==================================================
# MAIN AUTOMATION
# ==================================================

def main():

    OUTPUT.mkdir(parents=True, exist_ok=True)

    items = load_news()
    item = choose_topic(items)

    if not item:
        log("No new topic found.")
        return

    title = item.get("title", "GTA News")
    url = item.get("url", "")

    log("Selected topic:", title)
    log("Model:", MODEL)

    article = read_article(url)

    script = generate_script(
        item,
        article
    )

    words = len(script.split())

    stamp = datetime.now(
        timezone.utc
    ).strftime("%Y%m%d_%H%M%S")

    assets = download_visuals(
        title,
        OUTPUT / f"assets_{stamp}"
    )

    audio = OUTPUT / f"voice_{stamp}.mp3"

    audio = asyncio.run(
        generate_voice(script, audio)
    )

    duration = audio_duration(audio)

    log("Audio duration:", round(duration, 1))
    log("Script words:", words)

    if not MIN_AUDIO <= duration <= MAX_AUDIO:
        raise RuntimeError(
            "Video duration outside the required range."
        )

    video, subtitles = create_video(
        title,
        script,
        audio,
        duration,
        stamp,
        assets
    )

    report = {
        "title": title,
        "source": url,
        "model": MODEL,
        "words": words,
        "duration": duration,
        "video": str(video),
        "visual_assets": [
            {
                "title": a["title"],
                "source": a["source"],
                "license": a["license"],
                "author": a["author"]
            }
            for a in assets
        ],
        "script": script
    }

    report_path = OUTPUT / f"gta_vi_{stamp}_report.json"

    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    credits = OUTPUT / f"gta_vi_{stamp}_credits.txt"

    with credits.open("w", encoding="utf-8") as file:

        for asset in assets:

            file.write(
                f"{asset['title']}\n"
                f"Author: {asset['author']}\n"
                f"License: {asset['license']}\n"
                f"Source: {asset['source']}\n\n"
            )

    log("VIDEO SUCCESSFULLY GENERATED")
    log("VIDEO:", video)
    log("SUBTITLES:", subtitles)
    log("CREDITS:", credits)
    log("REPORT:", report_path)


if __name__ == "__main__":
    main()
