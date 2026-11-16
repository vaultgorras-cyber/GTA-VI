
import os
import re
import json
import asyncio
import subprocess
import shutil
import urllib.request
import urllib.error
import time

from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
import edge_tts

from config import DATA, OUTPUT


# ==========================================
# CONFIGURATION
# ==========================================

WIDTH = 1920
HEIGHT = 1080

MIN_AUDIO_SECONDS = 240
MAX_AUDIO_SECONDS = 420

SCENE_SECONDS = 20

API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()

MODEL = os.getenv(
    "OPENROUTER_MODEL",
    "openrouter/free"
)

MIN_WORDS = 600
MAX_SCRIPT_ATTEMPTS = 3


# ==========================================
# LOAD NEWS
# ==========================================

def load_news():

    try:
        data = json.loads(
            (DATA / "candidates.json").read_text(
                encoding="utf-8"
            )
        )

        items = data.get("items", [])

        return items if isinstance(items, list) else []

    except Exception as error:

        print("News loading error:", error)
        return []


# ==========================================
# OPENROUTER RESPONSE
# ==========================================

def extract_script(result):

    if not isinstance(result, dict):
        return ""

    choices = result.get("choices", [])

    if not choices:
        return ""

    choice = choices[0]

    if not isinstance(choice, dict):
        return ""

    message = choice.get("message", {})

    if not isinstance(message, dict):
        return ""

    content = message.get("content")

    if isinstance(content, str):
        return content.strip()

    if isinstance(content, list):

        parts = []

        for part in content:

            if isinstance(part, dict):

                text = part.get("text", "")

                if text:
                    parts.append(str(text))

        return "\n".join(parts).strip()

    return ""


# ==========================================
# GENERATE SCRIPT WITH OPENROUTER
# ==========================================

def request_script(item):

    if not API_KEY:

        raise RuntimeError(
            "OPENROUTER_API_KEY is missing in GitHub Secrets."
        )

    title = item.get(
        "title",
        "GTA VI Update"
    )

    summary = item.get("summary", "")

    url = item.get("url", "")

    prompt = f"""
You are a professional American English gaming journalist.

Write a complete YouTube news and analysis narration
about the following GTA VI topic.

TOPIC:
{title}

SOURCE SUMMARY:
{summary}

SOURCE URL:
{url}

REQUIREMENTS:

- Write between 650 and 750 spoken words.
- Use natural American English.
- Aim for approximately five minutes of narration.
- Begin with an engaging introduction.
- Explain the available information clearly.
- Provide useful context and analysis.
- Separate confirmed facts from speculation.
- Never invent quotes, announcements, dates or facts.
- Do not repeat information just to increase length.
- Explain what remains unknown.
- End with a concise conclusion.
- Return only the narration.
- Do not include headings.
- Do not include bullet points.
- Do not include markdown.
- Do not include stage directions.

If the source contains limited information,
be honest about it. Never invent facts.

The output must be a complete narration, not a summary.
"""

    for attempt in range(1, MAX_SCRIPT_ATTEMPTS + 1):

        print(
            f"OpenRouter attempt {attempt}/{MAX_SCRIPT_ATTEMPTS}"
        )

        payload = {
            "model": MODEL,

            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are an accurate professional gaming "
                        "journalist. Always return complete narration. "
                        "Never fabricate information."
                    )
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],

            "temperature": 0.5,
            "max_tokens": 2200
        }

        request = urllib.request.Request(
            "https://openrouter.ai/api/v1/chat/completions",

            data=json.dumps(payload).encode("utf-8"),

            headers={
                "Authorization": f"Bearer {API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/",
                "X-Title": "GTA VI News Automation"
            },

            method="POST"
        )

        try:

            with urllib.request.urlopen(
                request,
                timeout=150
            ) as response:

                result = json.loads(
                    response.read().decode("utf-8")
                )

            script = extract_script(result)

            words = len(script.split())

            choice = (
                result.get("choices", [{}])[0]
                if result.get("choices")
                else {}
            )

            print(
                "OpenRouter finish reason:",
                choice.get("finish_reason", "unknown")
            )

            print(
                "Generated script words:",
                words
            )

            print(
                "OpenRouter response preview:",
                script[:250]
            )

            if words >= MIN_WORDS:

                print("Complete script accepted.")

                return script

            print(
                "Response too short. Trying again..."
            )

        except urllib.error.HTTPError as error:

            details = error.read().decode(
                "utf-8",
                errors="replace"
            )

            print(
                "OpenRouter HTTP error:",
                error.code,
                details[:1000]
            )

        except Exception as error:

            print(
                "OpenRouter error:",
                str(error)
            )

        if attempt < MAX_SCRIPT_ATTEMPTS:

            time.sleep(4)

    raise RuntimeError(
        "OpenRouter failed to generate a complete script "
        "after three attempts. No video was created."
    )


# ==========================================
# FONT
# ==========================================

def get_font(size):

    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"
    ]

    for path in paths:

        if Path(path).exists():

            return ImageFont.truetype(
                path,
                size
            )

    return ImageFont.load_default()


# ==========================================
# TEXT WRAPPING
# ==========================================

def wrap_text(draw, text, selected_font, max_width):

    lines = []

    current = ""

    for word in text.split():

        test = (current + " " + word).strip()

        width = draw.textbbox(
            (0, 0),
            test,
            font=selected_font
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


# ==========================================
# ORIGINAL GRAPHICS
# ==========================================

def make_scene(title, number, path):

    image = Image.new(
        "RGB",
        (WIDTH, HEIGHT),
        (10, 18, 45)
    )

    draw = ImageDraw.Draw(image)

    draw.ellipse(
        (1050, -200, 2150, 900),
        outline=(238, 70, 160),
        width=18
    )

    draw.ellipse(
        (-400, 450, 700, 1500),
        outline=(20, 220, 220),
        width=16
    )

    draw.rectangle(
        (75, 70, 1845, 1010),
        outline=(255, 210, 80),
        width=5
    )

    draw.text(
        (125, 125),
        "GTA VI NEWS & ANALYSIS",
        font=get_font(45),
        fill=(255, 210, 80)
    )

    selected_font = get_font(78)

    y = 340

    for line in wrap_text(
        draw,
        title.upper(),
        selected_font,
        1650
    )[:4]:

        draw.text(
            (125, y),
            line,
            font=selected_font,
            fill="white",
            stroke_width=3,
            stroke_fill="black"
        )

        y += 105

    draw.text(
        (125, 850),
        "LATEST NEWS AND ANALYSIS",
        font=get_font(35),
        fill=(180, 230, 255)
    )

    draw.text(
        (1550, 950),
        f"SCENE {number:02d}",
        font=get_font(28),
        fill=(255, 210, 80)
    )

    image.save(path, quality=92)


# ==========================================
# VOICE GENERATION
# ==========================================

async def generate_voice(script, output_path):

    voices = [
        "en-US-GuyNeural",
        "en-US-ChristopherNeural",
        "en-US-AriaNeural"
    ]

    for voice in voices:

        for attempt in range(2):

            try:

                if output_path.exists():
                    output_path.unlink()

                await edge_tts.Communicate(
                    script,
                    voice,
                    rate="-5%"
                ).save(str(output_path))

                if (
                    output_path.exists()
                    and output_path.stat().st_size > 1000
                ):

                    print(
                        "Voice generated:",
                        voice
                    )

                    return output_path

            except Exception as error:

                print(
                    "Edge TTS error:",
                    voice,
                    str(error)
                )

            await asyncio.sleep(3)

    # Backup voice if Edge TTS is unavailable.

    espeak = (
        shutil.which("espeak-ng")
        or shutil.which("espeak")
    )

    if espeak:

        wav_path = output_path.with_suffix(".wav")

        subprocess.run(
            [
                espeak,
                "-v", "en-us",
                "-s", "145",
                "-w", str(wav_path),
                script
            ],
            check=True
        )

        if (
            wav_path.exists()
            and wav_path.stat().st_size > 1000
        ):

            print("Backup voice generated using eSpeak.")

            return wav_path

    raise RuntimeError(
        "Could not generate narration with any voice provider."
    )


# ==========================================
# AUDIO DURATION
# ==========================================

def get_audio_duration(path):

    result = subprocess.run(
        [
            "ffprobe",
            "-v", "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path)
        ],

        capture_output=True,
        text=True,
        check=True
    )

    return float(result.stdout.strip())


# ==========================================
# SUBTITLE TIMESTAMPS
# ==========================================

def srt_time(seconds):

    milliseconds = int(seconds * 1000)

    hours = milliseconds // 3600000
    milliseconds %= 3600000

    minutes = milliseconds // 60000
    milliseconds %= 60000

    secs = milliseconds // 1000
    milliseconds %= 1000

    return (
        f"{hours:02}:"
        f"{minutes:02}:"
        f"{secs:02},"
        f"{milliseconds:03}"
    )


# ==========================================
# CREATE SUBTITLES
# ==========================================

def create_subtitles(script, duration, path):

    sentences = re.split(
        r'(?<=[.!?])\s+',
        script.strip()
    )

    sentences = [
        sentence.strip()
        for sentence in sentences
        if sentence.strip()
    ]

    total_words = sum(
        len(sentence.split())
        for sentence in sentences
    )

    if total_words == 0:

        raise RuntimeError(
            "Cannot create subtitles: script is empty."
        )

    current_time = 0.0

    blocks = []

    counter = 1

    for sentence in sentences:

        words = sentence.split()

        sentence_duration = (
            duration * len(words) / total_words
        )

        chunks = [
            words[index:index + 12]
            for index in range(0, len(words), 12)
        ]

        chunk_time = current_time

        for chunk in chunks:

            text = " ".join(chunk)

            part_duration = (
                sentence_duration
                * len(chunk)
                / len(words)
            )

            end_time = min(
                duration,
                chunk_time + part_duration
            )

            blocks.append(
                f"{counter}\n"
                f"{srt_time(chunk_time)} --> "
                f"{srt_time(end_time)}\n"
                f"{text}\n"
            )

            counter += 1

            chunk_time = end_time

        current_time += sentence_duration

    path.write_text(
        "\n".join(blocks),
        encoding="utf-8"
    )

    print("Subtitles created:", path)


# ==========================================
# CREATE VIDEO
# ==========================================

def create_video(
    title,
    script,
    audio,
    duration,
    stamp
):

    scenes = []

    total_scenes = int(
        (duration + SCENE_SECONDS - 1)
        // SCENE_SECONDS
    )

    for index in range(total_scenes):

        scene = OUTPUT / (
            f"scene_{stamp}_{index:02d}.jpg"
        )

        make_scene(
            title,
            index + 1,
            scene
        )

        scenes.append(scene)

    concat_file = OUTPUT / f"scenes_{stamp}.txt"

    with concat_file.open(
        "w",
        encoding="utf-8"
    ) as file:

        for index, scene in enumerate(scenes):

            remaining = (
                duration - index * SCENE_SECONDS
            )

            scene_duration = min(
                SCENE_SECONDS,
                remaining
            )

            file.write(
                f"file '{scene.resolve()}'\n"
            )

            file.write(
                f"duration {scene_duration:.3f}\n"
            )

        file.write(
            f"file '{scenes[-1].resolve()}'\n"
        )

    subtitle_path = OUTPUT / f"gta_vi_{stamp}.srt"

    create_subtitles(
        script,
        duration,
        subtitle_path
    )

    video_path = OUTPUT / f"gta_vi_{stamp}.mp4"

    subtitle_filter_path = (
        str(subtitle_path.resolve())
        .replace("\\", "/")
        .replace(":", "\\:")
        .replace("'", r"\'")
    )

    video_filter = (
        "fps=25,"
        "scale=1920:1080,"
        "format=yuv420p,"
        f"subtitles='{subtitle_filter_path}'"
    )

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_file),
            "-i", str(audio),
            "-vf", video_filter,
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-c:a", "aac",
            "-b:a", "192k",
            "-t", f"{duration:.3f}",
            "-shortest",
            "-movflags", "+faststart",
            str(video_path)
        ],
        check=True
    )

    return video_path


# ==========================================
# MAIN
# ==========================================

def main():

    OUTPUT.mkdir(
        parents=True,
        exist_ok=True
    )

    items = load_news()

    if not items:

        print("No new GTA VI topics found.")

        return

    item = items[0]

    title = item.get(
        "title",
        "GTA VI Update"
    )

    print("================================")
    print("GTA VI VIDEO GENERATOR")
    print("================================")

    print("Selected topic:", title)

    print("Using model:", MODEL)

    # Generate narration script.

    script = request_script(item)

    word_count = len(script.split())

    print("Final script words:", word_count)

    # Unique filenames.

    stamp = datetime.now(
        timezone.utc
    ).strftime("%Y%m%d_%H%M%S")

    audio_path = OUTPUT / f"voice_{stamp}.mp3"

    # Generate voice.

    audio = asyncio.run(
        generate_voice(
            script,
            audio_path
        )
    )

    # Verify actual audio duration.

    duration = get_audio_duration(audio)

    print(
        f"Actual narration duration: {duration:.1f} seconds"
    )

    if duration < MIN_AUDIO_SECONDS:

        raise RuntimeError(
            f"Narration too short: {duration:.1f}s. "
            f"Minimum required: {MIN_AUDIO_SECONDS}s. "
            "Video cancelled."
        )

    if duration > MAX_AUDIO_SECONDS:

        raise RuntimeError(
            f"Narration too long: {duration:.1f}s. "
            f"Maximum allowed: {MAX_AUDIO_SECONDS}s. "
            "Video cancelled."
        )

    # Create video.

    video = create_video(
        title,
        script,
        audio,
        duration,
        stamp
    )

    # Save script and source.

    script_path = OUTPUT / f"gta_vi_{stamp}.txt"

    script_path.write_text(
        f"TITLE: {title}\n"
        f"SOURCE: {item.get('url', '')}\n"
        f"MODEL: {MODEL}\n"
        f"WORDS: {word_count}\n"
        f"AUDIO DURATION: {duration:.1f} seconds\n\n"
        f"SCRIPT:\n{script}",
        encoding="utf-8"
    )

    print("================================")
    print("VIDEO SUCCESSFULLY GENERATED")
    print("VIDEO:", video)
    print("AUDIO:", audio)
    print("DURATION:", round(duration, 1), "seconds")
    print("SUBTITLES:", OUTPUT / f"gta_vi_{stamp}.srt")
    print("================================")


if __name__ == "__main__":
    main()
