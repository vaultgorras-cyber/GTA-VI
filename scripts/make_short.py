
import os
import re
import json
import html
import time
import asyncio
import subprocess
import urllib.request
import urllib.parse

from pathlib import Path
from datetime import datetime, timezone
from html.parser import HTMLParser

import edge_tts

from config import DATA, OUTPUT


# ============================================================
# CONFIGURACIÓN
# ============================================================

WIDTH = 1920
HEIGHT = 1080
FPS = 30

MIN_AUDIO = 240
MAX_AUDIO = 420

MIN_WORDS = 600
MAX_WORDS = 850

MODEL = os.getenv(
    "OPENROUTER_MODEL",
    "nvidia/nemotron-3-ultra-550b-a55b:free"
).strip()

OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()

VOICE = os.getenv(
    "VIDEO_VOICE",
    "en-US-ChristopherNeural"
).strip()

USER_AGENT = "GTAVI-404-Automation/2.0"

ASSETS = Path(__file__).resolve().parent.parent / "assets"
GAMEPLAY_DIR = ASSETS / "gameplay"
MUSIC_DIR = ASSETS / "music"
IMAGE_DIR = ASSETS / "images"

CANDIDATES_FILE = DATA / "candidates.json"
PUBLISHED_FILE = DATA / "published.json"

for folder in (OUTPUT, GAMEPLAY_DIR, MUSIC_DIR, IMAGE_DIR):
    folder.mkdir(parents=True, exist_ok=True)


def log(*args):
    print("[GTA VI]", *args, flush=True)


def run_command(command):
    subprocess.run(command, check=True)


# ============================================================
# HISTORIAL PARA EVITAR TEMAS REPETIDOS
# ============================================================

def load_history():
    if not PUBLISHED_FILE.exists():
        return []

    try:
        data = json.loads(
            PUBLISHED_FILE.read_text(encoding="utf-8")
        )

        if isinstance(data, list):
            return data

        return data.get("items", [])

    except Exception as error:
        log("History loading error:", error)
        return []


def save_history(item, report):
    history = load_history()

    history.append({
        "title": item.get("_clean_title", item.get("title", "")),
        "url": item.get("url", ""),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "video": str(report),
        "status": "generated_for_review"
    })

    PUBLISHED_FILE.write_text(
        json.dumps(
            {"items": history[-500:]},
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )


def already_used(item, history):
    url = str(item.get("url", "")).strip().lower()
    title = str(
        item.get("_clean_title", item.get("title", ""))
    ).strip().lower()

    for old in history:
        old_url = str(old.get("url", "")).strip().lower()
        old_title = str(old.get("title", "")).strip().lower()

        if url and old_url and url == old_url:
            return True

        if title and old_title and title == old_title:
            return True

    return False


# ============================================================
# NOTICIAS
# ============================================================

def load_news():
    if not CANDIDATES_FILE.exists():
        log("Candidates file not found.")
        return []

    try:
        data = json.loads(
            CANDIDATES_FILE.read_text(encoding="utf-8")
        )

        if isinstance(data, list):
            return data

        return data.get("items", [])

    except Exception as error:
        log("News loading error:", error)
        return []


def choose_topic(items):
    if not items:
        return None

    history = load_history()

    gta_pattern = re.compile(
        r"\b(?:GTA\s*(?:VI|6)|Grand Theft Auto\s*(?:VI|6))\b",
        re.IGNORECASE
    )

    valid = []

    for item in items:
        title = html.unescape(
            str(item.get("title", ""))
        ).strip()

        summary = html.unescape(
            str(item.get("summary", ""))
        ).strip()

        if not title or not gta_pattern.search(title):
            continue

        if len(title.split()) < 4:
            continue

        if already_used(item, history):
            log("Already used:", title[:100])
            continue

        item["_clean_title"] = title
        item["_clean_summary"] = summary

        valid.append(item)

    if not valid:
        log("No new suitable GTA VI topics.")
        return None

    def ranking(item):
        trending = bool(
            item.get("is_trending")
            or item.get("priority") == "trend"
        )

        score = int(
            item.get("trend_score", item.get("score", 0)) or 0
        )

        published = str(
            item.get("published", item.get("published_at", ""))
        )

        return int(trending), score, published

    valid.sort(key=ranking, reverse=True)

    return valid[0]


# ============================================================
# LECTURA DEL ARTÍCULO
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
        if tag.lower() in ("script", "style", "noscript"):
            if self.skip:
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

        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read(1000000).decode(
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
# GENERACIÓN DEL GUION
# ============================================================

def generate_script(item, article):
    if not OPENROUTER_KEY:
        raise RuntimeError("OPENROUTER_API_KEY is missing.")

    title = item.get("_clean_title", item.get("title", "GTA VI News"))
    summary = item.get("_clean_summary", item.get("summary", ""))
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
- Write between 650 and 800 spoken words.
- Aim for approximately five minutes of narration.
- Start with a strong but accurate hook.
- Explain the story and why it matters to GTA players.
- Distinguish confirmed facts from rumours and speculation.
- Never invent facts, dates, quotes or announcements.
- Explain what remains unknown.
- Use natural, engaging American English.
- No headings, bullets, markdown or production notes.
- Do not repeat the same point.
- Return only the spoken narration.
"""

    for attempt in range(1, 5):
        payload = {
            "model": MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a professional American gaming journalist. "
                        "Be accurate, engaging and concise. Never invent facts."
                    )
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "temperature": 0.25,
            "max_tokens": 2200
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

            log(f"Script attempt {attempt}: {words} words")

            if (
                MIN_WORDS <= words <= MAX_WORDS
                and choice.get("finish_reason") != "length"
            ):
                return script

            if words > MAX_WORDS:
                instruction = (
                    "Shorten this narration to 650-780 words. "
                    "Preserve confirmed facts and remove repetition. "
                    "Do not add facts. Return only the narration:\n\n"
                )
            else:
                instruction = (
                    "Expand this narration to 650-780 words using "
                    "only supported context. Do not invent facts. "
                    "Return only the narration:\n\n"
                )

            prompt = instruction + script

        except Exception as error:
            log("OpenRouter error:", error)
            time.sleep(3)

    raise RuntimeError(
        "Could not generate a narration within the required word limit."
    )


# ============================================================
# VOZ Y SINCRONIZACIÓN PALABRA POR PALABRA
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

    if audio_path.stat().st_size < 5000:
        raise RuntimeError("Generated audio is too small.")

    log("Voice generated:", VOICE)
    log("Word timing events:", len(word_events))

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

    # Edge TTS provides word boundary events with audio timing.
    if events:
        for index, event in enumerate(events, 1):
            start = event["offset"] / 10_000_000
            span = event["duration"] / 10_000_000

            end = start + max(span, 0.12)

            if start >= duration:
                continue

            end = min(end, duration)

            word = str(event["text"]).strip()

            if not word:
                continue

            blocks.append(
                f"{len(blocks) + 1}\n"
                f"{srt_stamp(start)} --> {srt_stamp(end)}\n"
                f"{word}\n"
            )

    # Fallback if the voice service provides no word events.
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

    log("Word-by-word subtitles saved:", path)


# ============================================================
# IMÁGENES DE APOYO CON LICENCIAS COMPATIBLES
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
        "gsrlimit": 15,
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

    found = []
    seen = set()

    for query in (
        title,
        "Miami skyline public domain",
        "Vice City Miami public domain"
    ):
        try:
            for asset in search_images(query):
                if asset["url"] in seen:
                    continue

                seen.add(asset["url"])
                found.append(asset)

        except Exception as error:
            log("Image search error:", error)

    downloaded = []

    for index, asset in enumerate(found[:8]):
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
# GAMEPLAY LOCAL O FONDO PROVISIONAL
# ============================================================

def find_local_gameplay():
    extensions = (".mp4", ".mkv", ".mov", ".webm")

    for path in GAMEPLAY_DIR.iterdir():
        if path.is_file() and path.suffix.lower() in extensions:
            if path.stat().st_size > 100000:
                log("Using local gameplay:", path.name)
                return path

    return None


def create_background(duration, output):
    gameplay = find_local_gameplay()

    if gameplay:
        return gameplay, True

    log("No local gameplay found. Creating temporary background.")

    run_command([
        "ffmpeg",
        "-y",
        "-f", "lavfi",
        "-i",
        f"color=c=#101522:s={WIDTH}x{HEIGHT}:r={FPS}:d={duration}",
        "-vf",
        (
            "drawbox=x=0:y=0:w=iw:h=ih:color=#17243a@0.35:"
            "t=fill,format=yuv420p"
        ),
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-t", str(duration),
        str(output)
    ])

    return output, False


# ============================================================
# MÚSICA LOCAL OPCIONAL
# ============================================================

def find_music():
    extensions = (".mp3", ".wav", ".m4a", ".aac", ".ogg")

    for path in MUSIC_DIR.iterdir():
        if path.is_file() and path.suffix.lower() in extensions:
            return path

    return None


# ============================================================
# MONTAJE FINAL
# ============================================================

def create_video(
    title,
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
        "-i", str(gameplay),
        "-i", str(audio)
    ])

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

    # Brief full-screen image cutaways, returning to gameplay.
    image_count = len(images)

    if image_count:
        interval = duration / (image_count + 1)

        for index, image in enumerate(images):
            input_index = 3 + index if music else 2 + index

            start = interval * (index + 1) - 3
            start = max(5, start)

            end = min(duration - 5, start + 6)

            output_label = f"scene{index}"

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
                f"[{output_label}]"
            )

            previous = output_label

    filters.append(
        f"[{previous}]"
        f"subtitles='{subtitle_filter}',"
        "format=yuv420p[outv]"
    )

    command.extend([
        "-filter_complex",
        ";".join(filters),
        "-map", "[outv]",
        "-map", "1:a"
    ])

    if music:
        music_index = 2
        command.extend([
            "-filter:a",
            f"volume=0.10",
            "-map", f"{music_index}:a"
        ])

    command.extend([
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "21",
        "-c:a", "aac",
        "-b:a", "192k",
        "-t", str(duration),
        "-shortest",
        "-movflags", "+faststart",
        str(video)
    ])

    run_command(command)

    return video


# ============================================================
# PROCESO PRINCIPAL
# ============================================================

def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)

    items = load_news()
    item = choose_topic(items)

    if not item:
        log("No new topic available. Nothing generated.")
        return

    title = item.get(
        "_clean_title",
        item.get("title", "GTA VI News")
    )

    source = str(item.get("url", ""))

    stamp = datetime.now(
        timezone.utc
    ).strftime("%Y%m%d_%H%M%S")

    log("Selected topic:", title)

    article = read_article(source)

    script = generate_script(item, article)

    word_count = len(script.split())

    log("Narration words:", word_count)

    work = OUTPUT / f"work_{stamp}"
    work.mkdir(parents=True, exist_ok=True)

    audio = OUTPUT / f"voice_{stamp}.mp3"

    audio, word_events = asyncio.run(
        generate_voice(script, audio)
    )

    duration = get_audio_duration(audio)

    log("Narration duration:", round(duration, 1), "seconds")

    if not MIN_AUDIO <= duration <= MAX_AUDIO:
        raise RuntimeError(
            "Narration duration is outside the configured range."
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

    log("Support images found:", len(images))

    video = create_video(
        title,
        gameplay,
        audio,
        duration,
        subtitles,
        images,
        stamp
    )

    report = {
        "title": title,
        "source": source,
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

    report_path.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    save_history(item, report_path)

    log("VIDEO GENERATED:", video)
    log("SUBTITLES:", subtitles)
    log("REPORT:", report_path)


if __name__ == "__main__":
    main()
