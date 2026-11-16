
import os
import json
import re
import asyncio
import subprocess
import shutil
import urllib.request
import urllib.error
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

TARGET_SECONDS = 300
MIN_AUDIO_SECONDS = 240
MAX_AUDIO_SECONDS = 360

SCENE_SECONDS = 20

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv(
    "OPENROUTER_MODEL",
    "openrouter/free"
)

VOICE = "en-US-GuyNeural"


# ==========================================
# LOAD NEWS
# ==========================================

def load():

    candidates_file = DATA / "candidates.json"

    try:
        data = json.loads(
            candidates_file.read_text(encoding="utf-8")
        )

        return data.get("items", [])

    except Exception as error:

        print("Error loading news:", error)
        return []


# ==========================================
# OPENROUTER SCRIPT GENERATION
# ==========================================

def request_script(item):

    if not OPENROUTER_API_KEY:
        raise RuntimeError(
            "Missing OPENROUTER_API_KEY GitHub secret."
        )

    title = item.get("title", "GTA VI Update")

    summary = re.sub(
        r"\s+",
        " ",
        item.get("summary", "")
    ).strip()

    url = item.get("url", "")

    prompt = f"""
You are a professional American English video journalist.

Write a complete, engaging YouTube news and analysis
script about this GTA VI topic.

TOPIC:
{title}

AVAILABLE SOURCE SUMMARY:
{summary}

SOURCE URL:
{url}

STRICT RULES:

1. Write between 700 and 800 spoken words.
2. Use natural American English.
3. Make the script suitable for approximately five minutes
   of narration.
4. Start with a compelling introduction.
5. Explain the available information clearly.
6. Separate confirmed facts from speculation.
7. Never invent quotes, dates, announcements, or facts.
8. Do not claim Rockstar confirmed anything unless
   the supplied source explicitly supports it.
9. Explain what is known and what remains uncertain.
10. Include useful analysis and context without repeating
    the same points to increase length.
11. Finish with a short conclusion.
12. Do not include stage directions.
13. Do not include camera directions.
14. Do not include headings, bullet points, or markdown.
15. Return only the narration script.

If the source contains very little information,
be transparent about that. Do not invent details
to fill the script.
"""

    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are an accurate gaming news journalist. "
                    "Never fabricate information."
                )
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        "temperature": 0.6,
        "max_tokens": 1800
    }

    request = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/",
            "X-Title": "GTA VI News Automation"
        },
        method="POST"
    )

    try:

        with urllib.request.urlopen(
            request,
            timeout=120
        ) as response:

            result = json.loads(
                response.read().decode("utf-8")
            )

    except urllib.error.HTTPError as error:

        details = error.read().decode(
            "utf-8",
            errors="replace"
        )

        raise RuntimeError(
            f"OpenRouter HTTP error {error.code}: {details}"
        )

    except Exception as error:

        raise RuntimeError(
            f"OpenRouter request failed: {error}"
        )

    try:

        script = result["choices"][0]["message"]["content"]

    except (KeyError, IndexError, TypeError):

        raise RuntimeError(
            "OpenRouter returned an invalid response."
        )

    if isinstance(script, list):

        script = " ".join(
            part.get("text", "")
            for part in script
            if isinstance(part, dict)
        )

    script = str(script).strip()

    word_count = len(script.split())

    print("Generated script words:", word_count)

    if word_count < 600:

        raise RuntimeError(
            "Generated script is too short. "
            "At least 600 words are required."
        )

    return script


# ==========================================
# FONTS
# ==========================================

def font(size):

    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"
    ]

    for path in paths:

        if Path(path).exists():
            return ImageFont.truetype(path, size)

    return ImageFont.load_default()


# ==========================================
# TEXT WRAPPING
# ==========================================

def wrap(draw, text, selected_font, max_width):

    lines = []
    line = ""

    for word in text.split():

        test = (line + " " + word).strip()

        width = draw.textbbox(
            (0, 0),
            test,
            font=selected_font
        )[2]

        if width <= max_width:

            line = test

        else:

            if line:
                lines.append(line)

            line = word

    if line:
        lines.append(line)

    return lines


# ==========================================
# ORIGINAL GRAPHICS
# ==========================================

def make_scene(title, subtitle, number, path):

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
        font=font(45),
        fill=(255, 210, 80)
    )

    selected_font = font(78)

    y = 340

    for line in wrap(
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
        subtitle[:65],
        font=font(35),
        fill=(180, 230, 255)
    )

    draw.text(
        (1550, 950),
        f"SCENE {number:02d}",
        font=font(28),
        fill=(255, 210, 80)
    )

    image.save(path, quality=92)


# ==========================================
# VOICE GENERATION
# ==========================================

async def edge_voice(text, path):

    voices = [
        "en-US-GuyNeural",
        "en-US-ChristopherNeural",
        "en-US-AriaNeural"
    ]

    for voice_name in voices:

        for attempt in range(2):

            try:

                if path.exists():
                    path.unlink()

                await edge_tts.Communicate(
                    text,
                    voice_name,
                    rate="+0%"
                ).save(str(path))

                if (
                    path.exists()
                    and path.stat().st_size > 1000
                ):

                    print(
                        "Narration created:",
                        voice_name
                    )

                    return path

            except Exception as error:

                print(
                    f"Voice error ({voice_name}): {error}"
                )

            await asyncio.sleep(3)

    espeak = (
        shutil.which("espeak-ng")
        or shutil.which("espeak")
    )

    if espeak:

        wav = path.with_suffix(".wav")

        subprocess.run(
            [
                espeak,
                "-v", "en-us",
                "-s", "145",
                "-w", str(wav),
                text
            ],
            check=True
        )

        if wav.exists() and wav.stat().st_size > 1000:

            print("Using backup voice.")

            return wav

    raise RuntimeError(
        "Could not generate narration."
    )


# ==========================================
# AUDIO DURATION
# ==========================================

def audio_duration(path):

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
# SUBTITLE GENERATION
# ==========================================

def timestamp(seconds):

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
        raise RuntimeError("No subtitle text available.")

    current_time = 0.0
    subtitle_number = 1

    blocks = []

    for sentence in sentences:

        word_count = len(sentence.split())

        sentence_duration = (
            duration * word_count / total_words
        )

        start = current_time
        end = min(
            duration,
            current_time + sentence_duration
        )

        words = sentence.split()

        # Keep subtitles readable.
        chunks = [
            " ".join(words[i:i + 12])
            for i in range(0, len(words), 12)
        ]

        chunk_words = sum(
            len(chunk.split())
            for chunk in chunks
        )

        chunk_time = start

        for chunk in chunks:

            part_duration = (
                sentence_duration
                * len(chunk.split())
                / chunk_words
            )

            part_end = min(
                duration,
                chunk_time + part_duration
            )

            blocks.append(
                f"{subtitle_number}\n"
                f"{timestamp(chunk_time)} --> "
                f"{timestamp(part_end)}\n"
                f"{chunk}\n"
            )

            subtitle_number += 1
            chunk_time = part_end

        current_time = end

    path.write_text(
        "\n".join(blocks),
        encoding="utf-8"
    )

    print("Subtitles created:", path)


# ==========================================
# VIDEO CREATION
# ==========================================

def create_video(
    title,
    script,
    audio,
    duration,
    stamp
):

    scene_paths = []

    total_scenes = max(
        1,
        int((duration + SCENE_SECONDS - 1) // SCENE_SECONDS)
    )

    for index in range(total_scenes):

        scene = OUTPUT / (
            f"scene_{stamp}_{index:02d}.jpg"
        )

        make_scene(
            title,
            "Latest GTA VI news and analysis",
            index + 1,
            scene
        )

        scene_paths.append(scene)

    concat_file = OUTPUT / f"scenes_{stamp}.txt"

    with concat_file.open(
        "w",
        encoding="utf-8"
    ) as file:

        for index, scene in enumerate(scene_paths):

            remaining = duration - (
                index * SCENE_SECONDS
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
            f"file '{scene_paths[-1].resolve()}'\n"
        )

    subtitle_path = OUTPUT / f"gta_vi_{stamp}.srt"

    create_subtitles(
        script,
        duration,
        subtitle_path
    )

    video_path = OUTPUT / f"gta_vi_{stamp}.mp4"

    # Escape characters for FFmpeg subtitles filter.
    subtitle_filter_path = str(
        subtitle_path.resolve()
    ).replace("\\", "/").replace(":", "\\:")

    subtitle_filter = (
        f"subtitles='{subtitle_filter_path}':"
        "force_style='FontName=DejaVu Sans,"
        "FontSize=20,"
        "PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H00000000,"
        "BorderStyle=1,"
        "Outline=2,"
        "Shadow=1,"
        "Alignment=2,"
        "MarginV=45'"
    )

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_file),
            "-i", str(audio),
            "-t", f"{duration:.3f}",
            "-vf",
            (
                "fps=25,"
                "scale=1920:1080,"
                "format=yuv420p,"
                + subtitle_filter
            ),
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-c:a", "aac",
            "-b:a", "192k",
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

    items = load()

    if not items:

        print("No new GTA VI topics found.")
        return

    item = items[0]

    title = item.get(
        "title",
        "GTA VI Update"
    )

    print("Selected topic:", title)

    # Generate the complete narration.
    script = request_script(item)

    stamp = datetime.now(
        timezone.utc
    ).strftime("%Y%m%d_%H%M%S")

    audio_path = OUTPUT / f"voice_{stamp}.mp3"

    audio = asyncio.run(
        edge_voice(
            script,
            audio_path
        )
    )

    duration = audio_duration(audio)

    print(
        f"Audio duration: {duration:.1f} seconds"
    )

    if duration < MIN_AUDIO_SECONDS:

        raise RuntimeError(
            f"Narration is too short ({duration:.1f}s). "
            "Video generation cancelled."
        )

    if duration > MAX_AUDIO_SECONDS:

        raise RuntimeError(
            f"Narration is too long ({duration:.1f}s). "
            "Video generation cancelled."
        )

    video_path = create_video(
        title,
        script,
        audio,
        duration,
        stamp
    )

    script_path = OUTPUT / f"gta_vi_{stamp}.txt"

    script_path.write_text(
        f"TITLE: {title}\n"
        f"SOURCE: {item.get('url', '')}\n"
        f"MODEL: {OPENROUTER_MODEL}\n"
        f"AUDIO DURATION: {duration:.1f} seconds\n\n"
        f"SCRIPT:\n{script}",
        encoding="utf-8"
    )

    print("--------------------------------")
    print("VIDEO SUCCESSFULLY GENERATED")
    print("Video:", video_path)
    print("Audio:", audio)
    print("Duration:", round(duration, 1), "seconds")
    print("--------------------------------")


if __name__ == "__main__":
    main()
