
import os
import re
import json
import html
import time
import asyncio
import subprocess
import urllib.request
import urllib.parse
import urllib.error
import email.utils

from pathlib import Path
from datetime import datetime, timezone
from html.parser import HTMLParser
from difflib import SequenceMatcher

import edge_tts

from config import DATA, OUTPUT


# ============================================================
# CONFIGURATION - FREE MODEL ONLY
# ============================================================

MODEL = "openrouter/free"

OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()

VOICE = "en-US-ChristopherNeural"

WIDTH = 1920
HEIGHT = 1080
FPS = 30

MIN_AUDIO = 240
MAX_AUDIO = 420

MIN_WORDS = 600
MAX_WORDS = 850

USER_AGENT = "GTAVI-404-Automation/4.0"

ROOT = Path(__file__).resolve().parent.parent

ASSETS = ROOT / "assets"
GAMEPLAY_DIR = ASSETS / "gameplay"
MUSIC_DIR = ASSETS / "music"

CANDIDATES_FILE = DATA / "candidates.json"
PUBLISHED_FILE = DATA / "published.json"
SEEN_FILE = DATA / "seen.json"

for folder in (DATA, OUTPUT, GAMEPLAY_DIR, MUSIC_DIR):
    folder.mkdir(parents=True, exist_ok=True)


# ============================================================
# GENERAL UTILITIES
# ============================================================

def log(*args):
    print("[GTA VI]", *args, flush=True)


def read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")

    temporary.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )

    temporary.replace(path)


def clean_text(value):
    value = html.unescape(str(value or ""))
    return re.sub(r"\s+", " ", value).strip()


def run_command(command):
    subprocess.run(command, check=True)


# ============================================================
# HISTORY AND DUPLICATE PROTECTION
# ============================================================

def load_history():
    data = read_json(PUBLISHED_FILE, [])

    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        return data.get("items", [])

    return []


def normalized_title(title):
    title = clean_text(title).lower()
    title = re.sub(r"[^a-z0-9 ]", " ", title)
    return re.sub(r"\s+", " ", title).strip()


def similar_title(first, second):
    first = normalized_title(first)
    second = normalized_title(second)

    if not first or not second:
        return False

    return SequenceMatcher(None, first, second).ratio() >= 0.88


def already_used(item, history):
    url = clean_text(item.get("url", "")).lower()
    title = item.get("_clean_title", item.get("title", ""))

    for old in history:
        old_url = clean_text(old.get("url", "")).lower()
        old_title = old.get("title", "")

        if url and old_url and url == old_url:
            return True

        if similar_title(title, old_title):
            return True

    return False


def mark_seen(item):
    seen = read_json(SEEN_FILE, {})

    if not isinstance(seen, dict):
        seen = {}

    url = clean_text(item.get("url", ""))

    if url:
        seen[url] = datetime.now(timezone.utc).isoformat()

    write_json(SEEN_FILE, seen)


def save_history(item, report_path):
    history = load_history()

    history.append({
        "title": item.get(
            "_clean_title",
            item.get("title", "")
        ),
        "url": item.get("url", ""),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "video": str(report_path),
        "status": "generated_for_review"
    })

    write_json(
        PUBLISHED_FILE,
        {"items": history[-500:]}
    )

    mark_seen(item)


# ============================================================
# NEWS CANDIDATES
# ============================================================

def load_news():
    data = read_json(CANDIDATES_FILE, {})

    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        return data.get("items", [])

    return []


def choose_topic(items):
    history = load_history()
    valid = []

    gta_pattern = re.compile(
        r"\b(?:GTA\s*(?:VI|6)|Grand Theft Auto\s*(?:VI|6))\b",
        re.IGNORECASE
    )

    for item in items:
        title = clean_text(item.get("title", ""))

        if not gta_pattern.search(title):
            continue

        if len(title.split()) < 4:
            continue

        if any(x in title.lower() for x in (
            "gta v", "gta 5", "gta online"
        )):
            continue

        item["_clean_title"] = title
        item["_clean_summary"] = clean_text(
            item.get("summary", "")
        )

        if already_used(item, history):
            log("Skipping previously used topic:", title)
            continue

        valid.append(item)

    if not valid:
        return None

    valid.sort(
        key=lambda x: (
            bool(x.get("is_trending")),
            int(x.get("trend_score", x.get("score", 0)) or 0),
            str(x.get("published", x.get("published_at", "")))
        ),
        reverse=True
    )

    return valid[0]


# ============================================================
# ARTICLE READER
# ============================================================

class ArticleParser(HTMLParser):

    SKIP = {"script", "style", "noscript", "svg", "nav", "footer"}

    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip_count = 0

    def handle_starttag(self, tag, attrs):
        if tag.lower() in self.SKIP:
            self.skip_count += 1

    def handle_endtag(self, tag):
        if tag.lower() in self.SKIP and self.skip_count:
            self.skip_count -= 1

    def handle_data(self, data):
        if not self.skip_count:
            value = clean_text(data)
            if value:
                self.parts.append(value)


def read_article(url):
    if not url.startswith(("http://", "https://")):
        return ""

    try:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": USER_AGENT}
        )

        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read(1_000_000).decode(
                "utf-8",
                errors="replace"
            )

        parser = ArticleParser()
        parser.feed(raw)

        return " ".join(parser.parts)[:9000]

    except Exception as error:
        log("Article unavailable:", error)
        return ""


# ============================================================
# FREE OPENROUTER SCRIPT GENERATION
# ============================================================

def generate_script(item, article):

    if not OPENROUTER_KEY:
        raise RuntimeError("OPENROUTER_API_KEY is missing.")

    title = item.get("_clean_title", item.get("title", "GTA VI News"))
    summary = item.get("_clean_summary", "")
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
{article[:7000]}

REQUIREMENTS:
- Write 650 to 800 spoken words.
- Aim for approximately five minutes.
- Start with an engaging factual hook.
- Explain why the story matters to GTA players.
- Separate confirmed facts from rumours.
- Never invent facts, dates, quotes or announcements.
- Explain what remains unknown.
- Use natural American English.
- No headings, markdown or bullet points.
- Avoid repetition.
- Return only the narration.
"""

    last_error = None

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
            "temperature": 0.3,
            "max_tokens": 2400
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
                result = json.loads(
                    response.read().decode("utf-8")
                )

            choice = result["choices"][0]
            script = choice["message"]["content"].strip()

            script = re.sub(
                r"^```(?:text)?\s*|\s*```$",
                "",
                script
            ).strip()

            words = len(script.split())

            log(
                f"Attempt {attempt}: {words} words. "
                f"Model: {result.get('model', MODEL)}"
            )

            if (
                MIN_WORDS <= words <= MAX_WORDS
                and choice.get("finish_reason") != "length"
            ):
                return script

            if words < MIN_WORDS:
                prompt = (
                    "Expand this narration to 650-800 words. "
                    "Use only supported facts. Never invent information.\n\n"
                    + script
                )
            else:
                prompt = (
                    "Shorten this narration to 650-800 words. "
                    "Remove repetition and preserve facts.\n\n"
                    + script
                )

        except urllib.error.HTTPError as error:

            last_error = error

            if error.code == 429:

                retry_after = error.headers.get("Retry-After")
                wait_seconds = 30 * attempt

                if retry_after:
                    try:
                        wait_seconds = int(retry_after)
                    except ValueError:
                        try:
                            retry_date = email.utils.parsedate_to_datetime(
                                retry_after
                            )
                            wait_seconds = max(
                                1,
                                int((
                                    retry_date
                                    - datetime.now(timezone.utc)
                                ).total_seconds())
                            )
                        except Exception:
                            pass

                log(
                    f"Free model rate limit. "
                    f"Waiting {wait_seconds} seconds."
                )

                if attempt < 3:
                    time.sleep(min(wait_seconds, 120))
                    continue

            body = error.read().decode(
                "utf-8",
                errors="replace"
            )

            raise RuntimeError(
                f"OpenRouter HTTP {error.code}: {body[:1000]}"
            ) from error

        except Exception as error:
            last_error = error
            log("OpenRouter error:", error)

            if attempt < 3:
                time.sleep(15 * attempt)

    raise RuntimeError(
        f"Could not generate a valid script. Last error: {last_error}"
    )


# ============================================================
# VOICE GENERATION
# ============================================================

async def generate_voice(script, audio_path):

    communicate = edge_tts.Communicate(
        script,
        VOICE,
        rate="-4%"
    )

    audio_data = []
    word_events = []

    async for chunk in communicate.stream():

        if chunk["type"] == "audio":
            audio_data.append(chunk["data"])

        elif chunk["type"] == "WordBoundary":
            word_events.append({
                "offset": chunk["offset"],
                "duration": chunk["duration"],
                "text": chunk["text"]
            })

    if not audio_data:
        raise RuntimeError("Voice generation returned no audio.")

    audio_path.write_bytes(b"".join(audio_data))

    return audio_path, word_events


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
# WORD-BY-WORD SUBTITLES
# ============================================================

def srt_stamp(seconds):

    milliseconds = max(0, int(seconds * 1000))

    hours, milliseconds = divmod(milliseconds, 3600000)
    minutes, milliseconds = divmod(milliseconds, 60000)
    seconds, milliseconds = divmod(milliseconds, 1000)

    return (
        f"{hours:02}:{minutes:02}:"
        f"{seconds:02},{milliseconds:03}"
    )


def make_word_subtitles(script, duration, events, path):

    blocks = []

    if events:

        for event in events:

            start = event["offset"] / 10_000_000
            span = event["duration"] / 10_000_000
            end = min(duration, start + max(span, 0.12))

            if start >= duration:
                continue

            word = str(event["text"]).strip()

            if not word:
                continue

            blocks.append(
                f"{len(blocks) + 1}\n"
                f"{srt_stamp(start)} --> {srt_stamp(end)}\n"
                f"{word}\n"
            )

    if not blocks:

        words = script.split()
        interval = duration / max(len(words), 1)

        for index, word in enumerate(words):

            start = index * interval
            end = min(duration, (index + 1) * interval)

            blocks.append(
                f"{index + 1}\n"
                f"{srt_stamp(start)} --> {srt_stamp(end)}\n"
                f"{word}\n"
            )

    path.write_text(
        "\n".join(blocks),
        encoding="utf-8"
    )


# ============================================================
# LICENSED SUPPORT IMAGES
# ============================================================

def allowed_license(value):

    text = html.unescape(str(value or "")).lower()

    if "noncommercial" in text or "no derivatives" in text:
        return False

    if re.search(r"\b(nc|nd)\b", text):
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
        "gsrlimit": 12,
        "prop": "imageinfo",
        "iiprop": "url|extmetadata",
        "iiurlwidth": 1920
    }

    url = (
        "https://commons.wikimedia.org/w/api.php?"
        + urllib.parse.urlencode(params)
    )

    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT}
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))

    assets = []

    pages = data.get("query", {}).get("pages", {})

    for page in pages.values():

        info = (page.get("imageinfo") or [{}])[0]
        metadata = info.get("extmetadata", {})

        license_name = metadata.get(
            "LicenseShortName", {}
        ).get("value", "")

        usage = metadata.get(
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
            "author": metadata.get(
                "Artist", {}
            ).get("value", "Unknown")
        })

    return assets


def download_news_images(title, folder):

    folder.mkdir(parents=True, exist_ok=True)

    downloaded = []

    try:
        found = search_images(title)
    except Exception as error:
        log("Image search error:", error)
        return downloaded

    seen_urls = set()

    for index, asset in enumerate(found):

        if len(downloaded) >= 5:
            break

        if asset["url"] in seen_urls:
            continue

        seen_urls.add(asset["url"])

        try:

            request = urllib.request.Request(
                asset["url"],
                headers={"User-Agent": USER_AGENT}
            )

            with urllib.request.urlopen(request, timeout=30) as response:
                content = response.read()

            path = folder / f"support_{index:02d}.jpg"
            path.write_bytes(content)

            from PIL import Image

            with Image.open(path) as image:
                image.verify()

            asset["path"] = str(path)
            downloaded.append(asset)

        except Exception as error:
            log("Image download failed:", error)

    return downloaded


# ============================================================
# LOCAL GAMEPLAY OR TEMPORARY BACKGROUND
# ============================================================

def find_local_gameplay():

    extensions = (".mp4", ".mkv", ".mov", ".webm")

    for path in sorted(GAMEPLAY_DIR.iterdir()):

        if (
            path.is_file()
            and path.suffix.lower() in extensions
            and path.stat().st_size > 100000
        ):
            log("Using local gameplay:", path.name)
            return path

    return None


def create_background(duration, output):

    gameplay = find_local_gameplay()

    if gameplay:
        return gameplay, True

    log("No local gameplay. Creating temporary background.")

    run_command([
        "ffmpeg",
        "-y",
        "-f", "lavfi",
        "-i",
        f"color=c=#101522:s={WIDTH}x{HEIGHT}:r={FPS}:d={duration}",
        "-vf",
        (
            "drawbox=x=0:y=0:w=iw:h=ih:"
            "color=#17243a@0.35:t=fill,"
            "format=yuv420p"
        ),
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-t", str(duration),
        str(output)
    ])

    return output, False


# ============================================================
# BACKGROUND MUSIC
# ============================================================

def find_music():

    extensions = (".mp3", ".wav", ".m4a", ".aac", ".ogg")

    for path in sorted(MUSIC_DIR.iterdir()):

        if path.is_file() and path.suffix.lower() in extensions:
            return path

    return None


# ============================================================
# VIDEO EDITING
# ============================================================

def create_video(
    gameplay,
    audio,
    duration,
    subtitles,
    images,
    stamp
):

    video = OUTPUT / f"gta_vi_{stamp}.mp4"
    music = find_music()

    command = ["ffmpeg", "-y"]

    command.extend([
        "-stream_loop", "-1",
        "-i", str(gameplay)
    ])

    command.extend(["-i", str(audio)])

    if music:
        command.extend([
            "-stream_loop", "-1",
            "-i", str(music)
        ])

    for image in images:
        command.extend([
            "-loop", "1",
            "-framerate", str(FPS),
            "-t", str(duration),
            "-i", image["path"]
        ])

    subtitle_filter = (
        str(subtitles.resolve())
        .replace("\\", "/")
        .replace(":", "\\:")
        .replace("'", "\\'")
    )

    filters = [
        (
            f"[0:v]scale={WIDTH}:{HEIGHT}:"
            "force_original_aspect_ratio=increase,"
            f"crop={WIDTH}:{HEIGHT},setsar=1[base]"
        )
    ]

    previous = "base"

    interval = duration / (len(images) + 1) if images else duration

    for index, image in enumerate(images):

        input_index = 3 + index if music else 2 + index

        start = max(5, interval * (index + 1) - 3)
        end = min(duration - 5, start + 6)

        if end <= start:
            continue

        filters.append(
            f"[{input_index}:v]"
            f"scale={WIDTH}:{HEIGHT}:"
            "force_original_aspect_ratio=increase,"
            f"crop={WIDTH}:{HEIGHT},setsar=1[img{index}]"
        )

        filters.append(
            f"[{previous}][img{index}]"
            f"overlay=0:0:"
            f"enable='between(t,{start:.2f},{end:.2f})'"
            f"[scene{index}]"
        )

        previous = f"scene{index}"

    filters.append(
        f"[{previous}]subtitles='{subtitle_filter}',"
        "format=yuv420p[outv]"
    )

    if music:

        filters.append(
            "[1:a]aresample=44100,volume=1.0[voice];"
            "[2:a]aresample=44100,volume=0.10[music];"
            "[voice][music]amix=inputs=2:"
            "duration=first:dropout_transition=2,"
            "alimiter=limit=0.95[aout]"
        )

    command.extend([
        "-filter_complex", ";".join(filters),
        "-map", "[outv]"
    ])

    if music:
        command.extend(["-map", "[aout]"])
    else:
        command.extend(["-map", "1:a"])

    command.extend([
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "21",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-t", str(duration),
        "-shortest",
        "-movflags", "+faststart",
        str(video)
    ])

    run_command(command)

    if not video.exists() or video.stat().st_size < 100000:
        raise RuntimeError("Final video is missing or too small.")

    return video


# ============================================================
# VIDEO REPORT
# ============================================================

def save_report(
    item,
    video,
    subtitles,
    script,
    duration,
    word_count,
    real_gameplay,
    images,
    stamp
):

    report = {
        "title": item.get(
            "_clean_title",
            item.get("title", "GTA VI News")
        ),
        "source": item.get("url", ""),
        "model": MODEL,
        "voice": VOICE,
        "word_count": word_count,
        "duration_seconds": duration,
        "resolution": f"{WIDTH}x{HEIGHT}",
        "video": str(video),
        "subtitles": str(subtitles),
        "gameplay_type": (
            "local_authorized_gameplay"
            if real_gameplay
            else "temporary_generated_background"
        ),
        "music_used": find_music() is not None,
        "images": [
            {
                "title": image.get("title"),
                "source": image.get("source"),
                "license": image.get("license"),
                "author": image.get("author")
            }
            for image in images
        ],
        "script": script
    }

    report_path = OUTPUT / f"gta_vi_{stamp}_report.json"

    write_json(report_path, report)

    return report_path


# ============================================================
# MAIN
# ============================================================

def main():

    items = load_news()

    log("Candidates loaded:", len(items))

    item = choose_topic(items)

    if not item:
        log("No new suitable GTA VI topic.")
        return

    title = item.get(
        "_clean_title",
        item.get("title", "GTA VI News")
    )

    source = item.get("url", "")

    stamp = datetime.now(
        timezone.utc
    ).strftime("%Y%m%d_%H%M%S")

    log("Selected topic:", title)

    article = read_article(source)

    if not article and not item.get("_clean_summary"):
        raise RuntimeError(
            "No article text or summary available. "
            "Skipping topic to avoid inventing information."
        )

    script = generate_script(item, article)

    word_count = len(script.split())

    log("Script words:", word_count)

    work = OUTPUT / f"work_{stamp}"
    work.mkdir(parents=True, exist_ok=True)

    audio = OUTPUT / f"voice_{stamp}.mp3"

    audio, word_events = asyncio.run(
        generate_voice(script, audio)
    )

    duration = get_audio_duration(audio)

    log("Voice duration:", round(duration, 1), "seconds")

    if not MIN_AUDIO <= duration <= MAX_AUDIO:
        raise RuntimeError(
            "Voice duration outside configured range."
        )

    subtitles = OUTPUT / f"gta_vi_{stamp}.srt"

    make_word_subtitles(
        script,
        duration,
        word_events,
        subtitles
    )

    background_file = work / "temporary_background.mp4"

    gameplay, real_gameplay = create_background(
        duration,
        background_file
    )

    images = download_news_images(
        title,
        work / "images"
    )

    log("Support images:", len(images))

    video = create_video(
        gameplay,
        audio,
        duration,
        subtitles,
        images,
        stamp
    )

    report_path = save_report(
        item,
        video,
        subtitles,
        script,
        duration,
        word_count,
        real_gameplay,
        images,
        stamp
    )

    save_history(item, report_path)

    log("VIDEO GENERATED:", video)
    log("SUBTITLES:", subtitles)
    log("REPORT:", report_path)

    if not real_gameplay:
        log(
            "WARNING: Temporary background used. "
            "Add authorized gameplay to assets/gameplay."
        )


if __name__ == "__main__":
    main()
