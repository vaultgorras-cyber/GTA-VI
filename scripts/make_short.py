
import os
import re
import json
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


WIDTH = 1920
HEIGHT = 1080
MIN_AUDIO_SECONDS = 240
MAX_AUDIO_SECONDS = 420
SCENE_SECONDS = 20

API_KEY = os.getenv("OPENROUTER_API_KEY", "")
MODEL = os.getenv("OPENROUTER_MODEL", "openrouter/free")


def load_news():
    try:
        data = json.loads(
            (DATA / "candidates.json").read_text(encoding="utf-8")
        )
        return data.get("items", [])
    except Exception as error:
        print("News loading error:", error)
        return []


def request_script(item):
    if not API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY is missing.")

    title = item.get("title", "GTA VI Update")
    summary = item.get("summary", "")
    url = item.get("url", "")

    prompt = f"""
Write a professional YouTube news and analysis narration
in natural American English about GTA VI.

TOPIC: {title}
SOURCE SUMMARY: {summary}
SOURCE URL: {url}

Requirements:
- Write 750 to 850 spoken words.
- Aim for approximately five minutes of narration.
- Begin with an engaging introduction.
- Explain the available information and its context.
- Clearly distinguish confirmed facts from speculation.
- Never invent announcements, quotes, dates or facts.
- Do not repeat information just to increase length.
- Explain what remains unknown.
- Finish with a concise conclusion.
- Return only the narration.
- No headings, bullet points, markdown or stage directions.

If the source does not contain enough information,
be transparent. Never invent details.
"""

    payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are an accurate gaming journalist. "
                    "Never fabricate news or facts."
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
        with urllib.request.urlopen(request, timeout=120) as response:
            result = json.loads(
                response.read().decode("utf-8")
            )
    except urllib.error.HTTPError as error:
        details = error.read().decode(
            "utf-8", errors="replace"
        )
        raise RuntimeError(
            f"OpenRouter error {error.code}: {details}"
        )

    try:
        content = result["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise RuntimeError("Invalid OpenRouter response.")

    if isinstance(content, list):
        content = " ".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict)
        )

    script = str(content).strip()
    words = len(script.split())

    print("Generated script words:", words)

    if words < 650:
        raise RuntimeError(
            f"Script too short: {words} words. "
            "Video generation cancelled."
        )

    return script


def get_font(size):
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf"
    ]

    for path in paths:
        if Path(path).exists():
            return ImageFont.truetype(path, size)

    return ImageFont.load_default()


def wrap_text(draw, text, selected_font, max_width):
    lines = []
    current = ""

    for word in text.split():
        test = (current + " " + word).strip()

        if draw.textbbox(
            (0, 0), test, font=selected_font
        )[2] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word

    if current:
        lines.append(current)

    return lines


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
        draw, title.upper(), selected_font, 1650
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
                    print("Voice generated:", voice)
                    return output_path

            except Exception as error:
                print("Voice generation error:", error)

            await asyncio.sleep(3)

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
                "-s", "135",
                "-w", str(wav_path),
                script
            ],
            check=True
        )

        if wav_path.exists() and wav_path.stat().st_size > 1000:
            print("Backup voice generated.")
            return wav_path

    raise RuntimeError("Could not generate narration.")


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


def srt_time(seconds):
    milliseconds = int(seconds * 1000)

    hours = milliseconds // 3600000
    milliseconds %= 3600000

    minutes = milliseconds // 60000
    milliseconds %= 60000

    secs = milliseconds // 1000
    milliseconds %= 1000

    return (
        f"{hours:02}:{minutes:02}:"
        f"{secs:02},{milliseconds:03}"
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
        raise RuntimeError("No subtitle text.")

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
                sentence_duration * len(chunk) / len(words)
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


def create_video(title, script, audio, duration, stamp):
    scenes = []

    total_scenes = int(
        (duration + SCENE_SECONDS - 1) // SCENE_SECONDS
    )

    for index in range(total_scenes):
        scene = OUTPUT / (
            f"scene_{stamp}_{index:02d}.jpg"
        )

        make_scene(title, index + 1, scene)
        scenes.append(scene)

    concat_file = OUTPUT / f"scenes_{stamp}.txt"

    with concat_file.open("w", encoding="utf-8") as file:
        for index, scene in enumerate(scenes):
            remaining = duration - index * SCENE_SECONDS
            scene_duration = min(
                SCENE_SECONDS, remaining
            )

            file.write(f"file '{scene.resolve()}'\n")
            file.write(f"duration {scene_duration:.3f}\n")

        file.write(f"file '{scenes[-1].resolve()}'\n")

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
        "fps=25,scale=1920:1080,format=yuv420p,"
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


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)

    items = load_news()

    if not items:
        print("No new GTA VI topics found.")
        return

    item = items[0]
    title = item.get("title", "GTA VI Update")

    print("Selected topic:", title)
    print("Using model:", MODEL)

    script = request_script(item)

    stamp = datetime.now(
        timezone.utc
    ).strftime("%Y%m%d_%H%M%S")

    audio_path = OUTPUT / f"voice_{stamp}.mp3"

    audio = asyncio.run(
        generate_voice(script, audio_path)
    )

    duration = get_audio_duration(audio)

    print(f"Actual narration duration: {duration:.1f}s")

    if duration < MIN_AUDIO_SECONDS:
        raise RuntimeError(
            f"Narration too short: {duration:.1f}s. "
            "Minimum is 240 seconds. Video cancelled."
        )

    if duration > MAX_AUDIO_SECONDS:
        raise RuntimeError(
            f"Narration too long: {duration:.1f}s. "
            "Maximum is 360 seconds. Video cancelled."
        )

    video = create_video(
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
        f"MODEL: {MODEL}\n"
        f"AUDIO DURATION: {duration:.1f} seconds\n\n"
        f"SCRIPT:\n{script}",
        encoding="utf-8"
    )

    print("VIDEO GENERATED:", video)
    print("AUDIO DURATION:", round(duration, 1))
    print("SUBTITLES:", OUTPUT / f"gta_vi_{stamp}.srt")


if __name__ == "__main__":
    main()
