
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
from difflib import SequenceMatcher

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

USER_AGENT = "GTAVI-404-Automation/3.0"

ASSETS = Path(__file__).resolve().parent.parent / "assets"
GAMEPLAY_DIR = ASSETS / "gameplay"
MUSIC_DIR = ASSETS / "music"
IMAGE_DIR = ASSETS / "images"

CANDIDATES_FILE = DATA / "candidates.json"
PUBLISHED_FILE = DATA / "published.json"
SEEN_FILE = DATA / "seen.json"

for folder in (OUTPUT, GAMEPLAY_DIR, MUSIC_DIR, IMAGE_DIR):
    folder.mkdir(parents=True, exist_ok=True)


# ============================================================
# UTILIDADES
# ============================================================

def log(*args):
    print("[GTA VI]", *args, flush=True)


def run_command(command):
    subprocess.run(command, check=True)


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


def safe_filename(value):
    return re.sub(r"[^a-zA-Z0-9_-]", "_", str(value))


# ============================================================
# HISTORIAL Y PREVENCIÓN DE REPETICIONES
# ============================================================

def load_history():
    data = read_json(PUBLISHED_FILE, [])

    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        items = data.get("items", [])
        return items if isinstance(items, list) else []

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

    if first == second:
        return True

    similarity = SequenceMatcher(
        None, first, second
    ).ratio()

    return similarity >= 0.88


def already_used(item, history):
    url = clean_text(item.get("url", "")).lower()
    title = clean_text(
        item.get("_clean_title", item.get("title", ""))
    )

    for old in history:
        old_url = clean_text(old.get("url", "")).lower()
        old_title = clean_text(old.get("title", ""))

        if url and old_url and url == old_url:
            return True

        if similar_title(title, old_title):
            return True

    return False


def mark_seen(item):
    """
    El radar utiliza seen.json como diccionario de URLs.
    Marcamos la noticia después de generar el vídeo correctamente.
    """

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
        "topic_id": item.get("topic_id", ""),
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
# CANDIDATOS
# ============================================================

def load_news():
    data = read_json(CANDIDATES_FILE, {})

    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        items = data.get("items", [])
        return items if isinstance(items, list) else []

    return []


def choose_topic(items):
    history = load_history()
    valid = []

    gta_pattern = re.compile(
        r"\b(?:GTA\s*(?:VI|6)|Grand Theft Auto\s*(?:VI|6))\b",
        re.IGNORECASE
    )

    blocked = (
        "gta v",
        "gta 5",
        "grand theft auto v",
        "gta online"
    )

    for item in items:
        title = clean_text(item.get("title", ""))
        summary = clean_text(item.get("summary", ""))

        if not title or not gta_pattern.search(title):
            continue

        if any(term in title.lower() for term in blocked):
            continue

        if len(title.split()) < 4:
            continue

        if already_used(item, history):
            log("Previously used topic:", title[:100])
            continue

        item["_clean_title"] = title
        item["_clean_summary"] = summary

        valid.append(item)

    if not valid:
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

    SKIP_TAGS = {
        "script", "style", "noscript",
        "svg", "nav", "footer"
    }

    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag.lower() in self.SKIP_TAGS:
            self.skip += 1

    def handle_endtag(self, tag):
        if tag.lower() in self.SKIP_TAGS and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            text = clean_text(data)
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
- Start with an engaging but accurate hook.
- Explain the story and why it matters to GTA players.
- Separate confirmed facts from rumours and speculation.
- Never invent facts, dates, quotes or announcements.
- Explain what remains unknown.
- Use natural, engaging American English.
- No headings, bullets, markdown or production notes.
- Do not repeat the same point.
- Do not present speculation as official Rockstar information.
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
                        "Be accurate, engaging and concise. "
                        "Never invent facts."
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
                    "Shorten this narration to 650-800 words. "
                    "Preserve supported facts and remove repetition. "
                    "Do not add facts. Return only the narration:\n\n"
                )
            else:
                instruction = (
                    "Expand this narration to 650-800 words using "
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
# VOZ Y SUBTÍTULOS PALABRA POR PALABRA
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

    # Fallback when word timing is unavailable.
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

    log("Word subtitles saved:", path)


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

    downloaded = []
    seen_urls = set()

    # Search only for the actual topic. Do not insert unrelated
    # generic city images just to fill the video.
    try:
        found = search_images(title)
    except Exception as error:
        log("Image search error:", error)
        return downloaded

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
# GAMEPLAY LOCAL O FONDO PROVISIONAL
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

    log("No local gameplay found. Creating temporary background.")

    run_command([
        "ffmpeg",
        "-y",
        "-f", "lavfi",
        "-i",
        (
            f"color=c=#101522:"
            f"s={WIDTH}x{HEIGHT}:r={FPS}:d={duration}"
        ),
        "-vf",
        (
            "drawbox=x=0:y=0:w=iw:h=ih:"
            "color=#17243a@0.35:t=fill,"
            "drawbox=x=0:y=ih*0.72:w=iw:h=ih*0.28:"
            "color=#080d18@0.30:t=fill,"
            "format=yuv420p"
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

    for path in sorted(MUSIC_DIR.iterdir()):
        if path.is_file() and path.suffix.lower() in extensions:
            return path

    return None


# ============================================================
# MONTAJE FINAL
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

    # Input 0: gameplay/background
    command.extend([
        "-stream_loop", "-1",
        "-i", str(gameplay)
    ])

    # Input 1: narration
    command.extend([
        "-i", str(audio)
    ])

    # Optional music input
    if music:
        command.extend([
            "-stream_loop", "-1",
            "-i", str(music)
        ])

    # Image inputs
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

    image_count = len(images)

    if image_count:
        interval = duration / (image_count + 1)

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
        f"[{previous}]"
        f"subtitles='{subtitle_filter}',"
        "format=yuv420p[outv]"
    )

    # Correct audio mixing: narration remains clear and music is quiet.
    if music:
        filters.append(
            "[1:a]aresample=44100,volume=1.0[voice];"
            "[2:a]aresample=44100,volume=0.10[music];"
            "[voice][music]amix=inputs=2:"
            "duration=first:dropout_transition=2,"
            "alimiter=limit=0.95[aout]"
        )

    command.extend([
        "-filter_complex",
        ";".join(filters),
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
        raise RuntimeError("The final video is missing or too small.")

    return video


# ============================================================
# INFORME
# ============================================================

def save_report(item, video, subtitles, script, duration,
                word_count, real_gameplay, images, stamp):

    report = {
        "title": item.get(
            "_clean_title",
            item.get("title", "GTA VI News")
        ),
        "source": item.get("url", ""),
        "topic_id": item.get("topic_id", ""),
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
# PROCESO PRINCIPAL
# ============================================================

def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)

    items = load_news()
    log("Candidates loaded:", len(items))

    item = choose_topic(items)

    if not item:
        log("No new suitable topic available.")
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

    if not article and not item.get("_clean_summary"):
        raise RuntimeError(
            "No article text or summary is available. "
            "Skipping this topic to avoid inventing information."
        )

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
            "Narration duration is outside the configured range. "
            "No final video was created."
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

    # Mark the topic as used only after the video and report succeed.
    save_history(item, report_path)

    log("VIDEO GENERATED:", video)
    log("SUBTITLES:", subtitles)
    log("REPORT:", report_path)

    if not real_gameplay:
        log(
            "WARNING: This video uses a temporary background. "
            "Add authorized gameplay to assets/gameplay."
        )


if __name__ == "__main__":
    main()
