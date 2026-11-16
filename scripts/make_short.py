
import json
import re
import asyncio
import subprocess
import shutil
import textwrap
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
import edge_tts

from config import DATA, OUTPUT


WIDTH = 1920
HEIGHT = 1080
TARGET_SECONDS = 300
SCENE_SECONDS = 20


def load():
    try:
        data = json.loads(
            (DATA / "candidates.json").read_text(
                encoding="utf-8"
            )
        )
        return data.get("items", [])
    except Exception:
        return []


def font(size):
    paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    ]

    for path in paths:
        if Path(path).exists():
            return ImageFont.truetype(path, size)

    return ImageFont.load_default()


def wrap(draw, text, selected_font, max_width):
    lines = []
    line = ""

    for word in text.split():
        test = (line + " " + word).strip()

        if draw.textbbox(
            (0, 0), test, font=selected_font
        )[2] <= max_width:
            line = test
        else:
            if line:
                lines.append(line)
            line = word

    if line:
        lines.append(line)

    return lines


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

    image.save(path)


async def edge_voice(text, path):
    voices = [
        "en-US-GuyNeural",
        "en-US-ChristopherNeural",
        "en-US-AriaNeural",
    ]

    for voice_name in voices:
        for attempt in range(2):
            try:
                if path.exists():
                    path.unlink()

                await edge_tts.Communicate(
                    text,
                    voice_name,
                    rate="+5%"
                ).save(str(path))

                if (
                    path.exists()
                    and path.stat().st_size > 1000
                ):
                    print(
                        "Narración creada:",
                        voice_name
                    )
                    return path

            except Exception as error:
                print(
                    f"Edge TTS {voice_name}: {error}"
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
                "-s", "150",
                "-w", str(wav),
                text
            ],
            check=True
        )

        if wav.exists() and wav.stat().st_size > 1000:
            print("Voz de respaldo generada.")
            return wav

    raise RuntimeError(
        "No se pudo generar la narración."
    )


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


def create_script(item):
    title = item.get("title", "GTA VI Update")
    summary = re.sub(
        r"\s+",
        " ",
        item.get("summary", "")
    ).strip()

    # El guion solo utiliza información disponible.
    # No inventamos noticias para llenar cinco minutos.
    paragraphs = [
        (
            "Welcome to GTA six News and Analysis. "
            f"Today we're looking at this topic: {title}."
        ),
        (
            "Here is what the available source says. "
            f"{summary if summary else 'There is currently limited verified information about this topic.'}"
        ),
        (
            "It is important to separate official information "
            "from community speculation. A popular video or "
            "online discussion does not automatically confirm "
            "that a claim is true."
        ),
        (
            "When evaluating GTA six news, we look for "
            "direct statements from Rockstar Games, "
            "original sources, and independent confirmation."
        ),
        (
            "We will continue monitoring new developments. "
            "Subscribe for more GTA six news and analysis."
        ),
    ]

    return "\n\n".join(paragraphs)


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)

    items = load()

    if not items:
        print("No hay temas nuevos.")
        return

    item = items[0]
    title = item.get("title", "GTA VI Update")
    script = create_script(item)

    stamp = datetime.now(
        timezone.utc
    ).strftime("%Y%m%d_%H%M%S")

    audio_path = OUTPUT / f"gta_vi_{stamp}.mp3"
    video_path = OUTPUT / f"gta_vi_{stamp}.mp4"

    audio = asyncio.run(
        edge_voice(script, audio_path)
    )

    duration = audio_duration(audio)

    if duration < 60:
        print(
            "La noticia no tiene información suficiente "
            "para un vídeo largo. Se omite."
        )
        return

    if duration > TARGET_SECONDS:
        print(
            "La narración supera los cinco minutos. "
            "Se ajustará al objetivo."
        )

    scene_paths = []

    total_scenes = max(
        1,
        int(TARGET_SECONDS / SCENE_SECONDS)
    )

    for index in range(total_scenes):
        scene = OUTPUT / (
            f"scene_{stamp}_{index:02d}.jpg"
        )

        make_scene(
            title,
            "Latest GTA VI community coverage",
            index + 1,
            scene
        )

        scene_paths.append(scene)

    concat_file = OUTPUT / f"scenes_{stamp}.txt"

    with concat_file.open(
        "w",
        encoding="utf-8"
    ) as file:
        for scene in scene_paths:
            file.write(
                f"file '{scene.resolve()}'\n"
            )
            file.write(
                f"duration {SCENE_SECONDS}\n"
            )

        file.write(
            f"file '{scene_paths[-1].resolve()}'\n"
        )

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_file),
            "-i", str(audio),
            "-t", str(TARGET_SECONDS),
            "-vf",
            "fps=25,scale=1920:1080,format=yuv420p",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-c:a", "aac",
            "-b:a", "192k",
            "-movflags", "+faststart",
            str(video_path)
        ],
        check=True
    )

    (OUTPUT / f"gta_vi_{stamp}.txt").write_text(
        f"TITLE: {title}\n"
        f"SOURCE: {item.get('url', '')}\n\n"
        f"SCRIPT:\n{script}",
        encoding="utf-8"
    )

    print("Vídeo horizontal generado:", video_path)


if __name__ == "__main__":
    main()
