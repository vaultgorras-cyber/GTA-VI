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


# ============================================================
# GTA VI AUTOMATIC VIDEO GENERATOR
# ============================================================

WIDTH = 1920
HEIGHT = 1080

MIN_AUDIO_SECONDS = 240
MAX_AUDIO_SECONDS = 420

MIN_WORDS = 600
MAX_WORDS = 850

SCENE_SECONDS = 12
MAX_ATTEMPTS = 3

MODEL = os.getenv(
    "OPENROUTER_MODEL",
    "nvidia/nemotron-3-ultra-550b-a55b:free"
).strip()

API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()

USER_AGENT = "GTA-VI-Automation/1.0"

FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"
]


def log(*message):
    print("[GTA VI]", *message, flush=True)


# ============================================================
# GENERAL FUNCTIONS
# ============================================================

def get_json(url, headers=None):

    request_headers = {
        "User-Agent": USER_AGENT
    }

    if headers:
        request_headers.update(headers)

    request = urllib.request.Request(
        url,
        headers=request_headers
    )

    with urllib.request.urlopen(request, timeout=40) as response:
        return json.loads(
            response.read().decode("utf-8")
        )


def load_news():

    path = DATA / "candidates.json"

    if not path.exists():
        return []

    try:
        data = json.loads(
            path.read_text(encoding="utf-8")
        )

        items = data.get("items", [])

        return [
            item for item in items
            if isinstance(item, dict)
        ]

    except Exception as error:
        log("News loading error:", error)
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
            item.get(
                "trend_score",
                item.get("score", 0)
            ) or 0
        )

        published = str(
            item.get(
                "published",
                item.get("published_at", "")
            )
        )

        return (
            int(bool(trending)),
            score,
            published
        )

    return sorted(
        items,
        key=ranking,
        reverse=True
    )[0]


# ============================================================
# READ NEWS ARTICLE
# ============================================================

class ArticleParser(HTMLParser):

    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):

        if tag.lower() in (
            "script",
            "style",
            "noscript",
            "svg"
        ):
            self.skip += 1

    def handle_endtag(self, tag):

        if tag.lower() in (
            "script",
            "style",
            "noscript",
            "svg"
        ) and self.skip:

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
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html"
            }
        )

        with urllib.request.urlopen(
            request,
            timeout=25
        ) as response:

            raw = response.read(
                1200000
            ).decode(
                "utf-8",
                errors="replace"
            )

        parser = ArticleParser()
        parser.feed(raw)

        text = " ".join(parser.parts)

        return re.sub(
            r"\s+",
            " ",
            text
        )[:9000]

    except Exception as error:

        log("Could not read article:", error)

        return ""


# ============================================================
# AUTOMATIC SCRIPT GENERATION
# ============================================================

def extract_script(result):

    try:

        content = result["choices"][0]["message"]["content"]

        if isinstance(content, str):
            return content.strip()

        if isinstance(content, list):

            return "\n".join(
                str(part.get("text", ""))
                for part in content
                if isinstance(part, dict)
                and part.get("text")
            ).strip()

    except Exception:
        pass

    return ""


def generate_script(item, article):

    if not API_KEY:
        raise RuntimeError(
            "OPENROUTER_API_KEY is missing."
        )

    title = str(
        item.get("title", "GTA News")
    )

    summary = str(
        item.get("summary", "")
    )

    source = str(
        item.get("url", "")
    )

    prompt = f"""
You are creating a professional GTA YouTube news video.

TOPIC:
{title}

NEWS SUMMARY:
{summary}

SOURCE:
{source}

ARTICLE TEXT:
{article}

REQUIREMENTS:

- Write 650 to 800 spoken words.
- Use natural American English.
- Target approximately five minutes.
- Start with an engaging and accurate hook.
- Explain the news in detail.
- Explain why it matters to GTA players.
- GTA VI, GTA V, GTA IV and other GTA games may be discussed.
- Comparisons with older GTA games are welcome when relevant.
- Clearly distinguish confirmed facts from rumours.
- Never invent announcements, quotes, dates or facts.
- Do not present speculation as confirmed information.
- Do not repeat sentences to increase the word count.
- Finish with a strong conclusion.
- Return only the spoken narration.
- No headings, bullet points or markdown.
"""

    for attempt in range(1, MAX_ATTEMPTS + 1):

        log(
            "Generating narration:",
            attempt,
            "of",
            MAX_ATTEMPTS
        )

        payload = {
            "model": MODEL,

            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a professional American gaming journalist. "
                        "Create accurate and engaging YouTube narrations. "
                        "Never invent facts."
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
            },

            method="POST"
        )

        try:

            with urllib.request.urlopen(
                request,
                timeout=180
            ) as response:

                result = json.loads(
                    response.read().decode("utf-8")
                )

            choice = result.get(
                "choices",
                [{}]
            )[0]

            script = extract_script(result)

            words = len(script.split())

            finish = choice.get(
                "finish_reason",
                "unknown"
            )

            log(
                "Script words:",
                words,
                "Finish:",
                finish
            )

            if (
                MIN_WORDS <= words <= MAX_WORDS
                and finish != "length"
            ):

                return script

        except urllib.error.HTTPError as error:

            details = error.read().decode(
                "utf-8",
                errors="replace"
            )

            log(
                "OpenRouter HTTP error:",
                error.code,
                details[:1000]
            )

        except Exception as error:

            log("OpenRouter error:", error)

        if attempt < MAX_ATTEMPTS:
            time.sleep(5)

    raise RuntimeError(
        "The AI did not produce a complete script."
    )


# ============================================================
# IMAGE SEARCH
# Wikimedia Commons: public domain and suitable CC licenses
# ============================================================

def acceptable_license(value):

    text = html.unescape(
        str(value or "")
    ).lower().replace("_", " ")

    if re.search(r"\b(nc|nd)\b", text):
        return False

    if (
        "noncommercial" in text
        or "no derivatives" in text
    ):
        return False

    accepted = (
        "public domain",
        "cc0",
        "cc by",
        "cc-by",
        "creative commons attribution",
        "creative commons zero"
    )

    return any(
        term in text
        for term in accepted
    )


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

    data = get_json(
        url,
        headers={
            "Api-User-Agent": USER_AGENT
        }
    )

    pages = data.get(
        "query", {}
    ).get(
        "pages", {}
    )

    assets = []

    for page in pages.values():

        info = (
            page.get("imageinfo") or [{}]
        )[0]

        metadata = info.get(
            "extmetadata", {}
        )

        license_name = metadata.get(
            "LicenseShortName", {}
        ).get("value", "")

        usage = metadata.get(
            "UsageTerms", {}
        ).get("value", "")

        if not (
            acceptable_license(license_name)
            or acceptable_license(usage)
        ):
            continue

        image_url = (
            info.get("thumburl")
            or info.get("url")
        )

        if not image_url:
            continue

        assets.append({
            "url": image_url,
            "title": page.get("title", ""),
            "source": info.get("descriptionurl", ""),
            "license": license_name or usage,
            "author": metadata.get(
                "Artist", {}
            ).get("value", "Unknown")
        })

    return assets


def download_visuals(title, folder):

    folder.mkdir(
        parents=True,
        exist_ok=True
    )

    queries = [
        title,
        "Grand Theft Auto VI",
        "Grand Theft Auto V",
        "Grand Theft Auto Vice City",
        "Miami city skyline",
        "Florida night city",
        "sports cars"
    ]

    found = []
    seen = set()

    for query in queries:

        try:

            results = search_images(query)

            for asset in results:

                key = asset["url"].split("?")[0]

                if key in seen:
                    continue

                seen.add(key)
                found.append(asset)

        except Exception as error:

            log(
                "Image search failed:",
                query,
                error
            )

        if len(found) >= 24:
            break

    downloaded = []

    for index, asset in enumerate(found[:24]):

        try:

            request = urllib.request.Request(
                asset["url"],
                headers={
                    "User-Agent": USER_AGENT
                }
            )

            with urllib.request.urlopen(
                request,
                timeout=45
            ) as response:

                content = response.read()

            path = folder / f"visual_{index:02d}.jpg"

            path.write_bytes(content)

            with Image.open(path) as image:
                image.verify()

            asset["path"] = str(path)

            downloaded.append(asset)

        except Exception as error:

            log(
                "Image rejected:",
                asset.get("title"),
                error
            )

    log(
        "Downloaded reusable visual assets:",
        len(downloaded)
    )

    return downloaded


# ============================================================
# NATURAL ENGLISH VOICE
# ============================================================

async def generate_voice(script, output):

    voices = [
        "en-US-ChristopherNeural",
        "en-US-GuyNeural",
        "en-US-AriaNeural"
    ]

    last_error = None

    for voice in voices:

        try:

            if output.exists():
                output.unlink()

            await edge_tts.Communicate(
                script,
                voice,
                rate="-4%",
                volume="+0%"
            ).save(str(output))

            if (
                output.exists()
                and output.stat().st_size > 5000
            ):

                log("Voice generated:", voice)

                return output

        except Exception as error:

            last_error = error

            log(
                "Voice failed:",
                voice,
                error
            )

            await asyncio.sleep(2)

    raise RuntimeError(
        "Natural voice generation failed. "
        f"Last error: {last_error}"
    )


def get_audio_duration(path):

    result = subprocess.run(
        [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path)
        ],

        capture_output=True,
        text=True,
        check=True
    )

    return float(
        result.stdout.strip()
    )


# ============================================================
# VIDEO GRAPHICS
# ============================================================

def get_font(size):

    for path in FONT_PATHS:

        if Path(path).exists():

            return ImageFont.truetype(
                path,
                size
            )

    return ImageFont.load_default()


def wrap_text(draw, text, font, max_width):

    lines = []
    current = ""

    for word in text.split():

        test = (
            current + " " + word
        ).strip()

        width = draw.textbbox(
            (0, 0),
            test,
            font=font
        )[2]

        if width <= max_width:

            current = test

        else:

            if current:
                lines.append(current)

            current = word

    if current:
        lines.append(current)

    return lines


def make_scene(image_path, title, number, output):

    with Image.open(image_path) as original:

        image = original.convert("RGB")

    scale = max(
        WIDTH / image.width,
        HEIGHT / image.height
    )

    image = image.resize(
        (
            int(image.width * scale),
            int(image.height * scale)
        ),
        Image.Resampling.LANCZOS
    )

    left = (
        image.width - WIDTH
    ) // 2

    top = (
        image.height - HEIGHT
    ) // 2

    image = image.crop(
        (
            left,
            top,
            left + WIDTH,
            top + HEIGHT
        )
    )

    overlay = Image.new(
        "RGBA",
        (WIDTH, HEIGHT),
        (0, 0, 0, 95)
    )

    image = Image.alpha_composite(
        image.convert("RGBA"),
        overlay
    )

    draw = ImageDraw.Draw(image)

    draw.text(
        (90, 80),
        "GTA NEWS  |  ANALYSIS",
        font=get_font(38),
        fill="white"
    )

    title_font = get_font(48)

    lines = wrap_text(
        draw,
        title.upper(),
        title_font,
        1500
    )[:2]

    y = 820

    for line in lines:

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
        f"{number:02d}",
        font=get_font(30),
        fill="white"
    )

    image.convert("RGB").save(
        output,
        quality=92
    )


# ============================================================
# SUBTITLES
# ============================================================

def srt_time(seconds):

    milliseconds = max(
        0,
        int(seconds * 1000)
    )

    hours, milliseconds = divmod(
        milliseconds,
        3600000
    )

    minutes, milliseconds = divmod(
        milliseconds,
        60000
    )

    secs, milliseconds = divmod(
        milliseconds,
        1000
    )

    return (
        f"{hours:02}:"
        f"{minutes:02}:"
        f"{secs:02},"
        f"{milliseconds:03}"
    )


def create_subtitles(script, duration, path):

    words = script.split()

    if not words:
        raise RuntimeError("Empty narration.")

    chunks = [
        words[index:index + 10]
        for index in range(0, len(words), 10)
    ]

    total_words = len(words)

    current = 0.0
    blocks = []

    for number, chunk in enumerate(chunks, 1):

        span = (
            duration * len(chunk) / total_words
        )

        end = min(
            duration,
            current + span
        )

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


# ============================================================
# VIDEO EDITING
# ============================================================

def create_video(
    title,
    script,
    audio,
    duration,
    stamp,
    assets
):

    if not assets:

        raise RuntimeError(
            "No reusable visual assets found. "
            "Video cancelled."
        )

    work = OUTPUT / f"work_{stamp}"

    work.mkdir(
        parents=True,
        exist_ok=True
    )

    scenes = []

    scene_count = max(
        1,
        math.ceil(duration / SCENE_SECONDS)
    )

    for index in range(scene_count):

        asset = assets[
            index % len(assets)
        ]

        scene = work / (
            f"scene_{index:03d}.jpg"
        )

        make_scene(
            asset["path"],
            title,
            index + 1,
            scene
        )

        scenes.append(scene)

    concat = work / "concat.txt"

    with concat.open(
        "w",
        encoding="utf-8"
    ) as file:

        for index, scene in enumerate(scenes):

            seconds = min(
                SCENE_SECONDS,
                duration - index * SCENE_SECONDS
            )

            file.write(
                f"file '{scene.resolve()}'\n"
            )

            file.write(
                f"duration {seconds:.3f}\n"
            )

        file.write(
            f"file '{scenes[-1].resolve()}'\n"
        )

    subtitles = OUTPUT / (
        f"gta_vi_{stamp}.srt"
    )

    create_subtitles(
        script,
        duration,
        subtitles
    )

    video = OUTPUT / (
        f"gta_vi_{stamp}.mp4"
    )

    subtitle_filter = (
        str(subtitles.resolve())
        .replace("\\", "/")
        .replace(":", "\\:")
        .replace("'", r"\'")
    )

    video_filter = (
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
            "-vf", video_filter,
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "21",
            "-c:a", "aac",
            "-b:a", "192k",
            "-t", f"{duration:.3f}",
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

    OUTPUT.mkdir(
        parents=True,
        exist_ok=True
    )

    items = load_news()

    item = choose_topic(items)

    if not item:

        log("No new GTA topic found.")

        return

    title = str(
        item.get("title", "GTA News")
    )

    source_url = str(
        item.get("url", "")
    )

    log("=" * 55)
    log("Selected topic:", title)
    log("Source:", source_url)
    log("Model:", MODEL)

    article = read_article(source_url)

    script = generate_script(
        item,
        article
    )

    word_count = len(script.split())

    stamp = datetime.now(
        timezone.utc
    ).strftime("%Y%m%d_%H%M%S")

    log("Narration created:", word_count, "words")

    assets = download_visuals(
        title,
        OUTPUT / f"assets_{stamp}"
    )

    audio_path = OUTPUT / f"voice_{stamp}.mp3"

    audio = asyncio.run(
        generate_voice(
            script,
            audio_path
        )
    )

    duration = get_audio_duration(audio)

    log(
        "Actual audio duration:",
        round(duration, 1),
        "seconds"
    )

    if not (
        MIN_AUDIO_SECONDS
        <= duration
        <= MAX_AUDIO_SECONDS
    ):

        raise RuntimeError(
            "Audio duration is outside the required range. "
            "Video cancelled."
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
        "source": source_url,
        "model": MODEL,
        "words": word_count,
        "duration_seconds": round(duration, 1),
        "video": str(video),
        "subtitles": str(subtitles),
        "script": script,
        "visual_assets": [
            {
                "title": asset.get("title"),
                "source": asset.get("source"),
                "license": asset.get("license"),
                "author": asset.get("author")
            }
            for asset in assets
        ]
    }

    report_path = OUTPUT / (
        f"gta_vi_{stamp}_report.json"
    )

    report_path.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    credits_path = OUTPUT / (
        f"gta_vi_{stamp}_credits.txt"
    )

    with credits_path.open(
        "w",
        encoding="utf-8"
    ) as file:

        file.write("VISUAL ASSET CREDITS\n\n")

        for asset in assets:

            file.write(
                f"Title: {asset.get('title')}\n"
                f"Author: {asset.get('author')}\n"
                f"License: {asset.get('license')}\n"
                f"Source: {asset.get('source')}\n\n"
            )

    log("=" * 55)
    log("VIDEO SUCCESSFULLY GENERATED")
    log("VIDEO:", video)
    log("AUDIO:", audio)
    log("SUBTITLES:", subtitles)
    log("CREDITS:", credits_path)
    log("REPORT:", report_path)
    log("=" * 55)


if __name__ == "__main__":
    main()
