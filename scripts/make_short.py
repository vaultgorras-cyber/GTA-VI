
import json
import re
import asyncio
import subprocess
import shutil
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
import edge_tts

from config import DATA, OUTPUT


def load():
    try:
        return json.loads(
            (DATA / "candidates.json").read_text(encoding="utf-8")
        ).get("items", [])
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
    output = []
    line = ""

    for word in text.split():
        test = (line + " " + word).strip()

        if draw.textbbox((0, 0), test, font=selected_font)[2] <= max_width:
            line = test
        else:
            if line:
                output.append(line)
            line = word

    if line:
        output.append(line)

    return output


async def voice(text, output_path):
    # Primera opción: Edge TTS con reintentos y varias voces.
    voices = [
        "en-US-GuyNeural",
        "en-US-ChristopherNeural",
        "en-US-AriaNeural",
    ]

    for voice_name in voices:
        for attempt in range(3):
            try:
                await edge_tts.Communicate(
                    text,
                    voice_name,
                    rate="+5%"
                ).save(str(output_path))

                if output_path.exists() and output_path.stat().st_size > 1000:
                    print(f"Voz generada con Edge TTS: {voice_name}")
                    return output_path

            except Exception as error:
                print(
                    f"Edge TTS fallo ({voice_name}), "
                    f"intento {attempt + 1}/3: {error}"
                )

            await asyncio.sleep(3 * (attempt + 1))

    # Segunda opción: voz local, sin depender de Microsoft.
    espeak = shutil.which("espeak-ng") or shutil.which("espeak")

    if espeak:
        wav_path = output_path.with_suffix(".wav")

        subprocess.run(
            [
                espeak,
                "-v", "en-us",
                "-s", "155",
                "-w", str(wav_path),
                text
            ],
            check=True
        )

        if wav_path.exists() and wav_path.stat().st_size > 1000:
            print("Voz generada con el sistema local de respaldo.")
            return wav_path

    raise RuntimeError(
        "No se pudo generar la voz. "
        "Fallaron Edge TTS y la voz local de respaldo."
    )


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)

    items = load()

    if not items:
        print("No hay novedades; no se crea vídeo.")
        return

    item = items[0]

    title = item.get("title", "GTA VI update")
    summary = re.sub(
        r"\s+",
        " ",
        item.get("summary", "")
    ).strip()

    script = (
        f"Here is a GTA six community update. "
        f"{title}. {summary[:350]}. "
        "Treat unconfirmed claims as rumours until Rockstar confirms them. "
        "Follow for more GTA six updates."
    )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    img = OUTPUT / f"gta_vi_{stamp}.jpg"
    audio_mp3 = OUTPUT / f"gta_vi_{stamp}.mp3"
    video = OUTPUT / f"gta_vi_{stamp}.mp4"

    canvas = Image.new("RGB", (1080, 1920), (10, 18, 45))
    draw = ImageDraw.Draw(canvas)

    draw.ellipse(
        (500, 160, 1250, 900),
        outline=(238, 70, 160),
        width=18
    )

    draw.ellipse(
        (-300, 1050, 650, 2000),
        outline=(20, 220, 220),
        width=16
    )

    draw.rectangle(
        (65, 90, 1015, 1830),
        outline=(255, 210, 80),
        width=5
    )

    selected_font = font(76)
    y = 570

    for line in wrap(
        draw,
        title.upper(),
        selected_font,
        850
    )[:6]:

        bounds = draw.textbbox(
            (0, 0),
            line,
            font=selected_font,
            stroke_width=3
        )

        x = (1080 - (bounds[2] - bounds[0])) // 2

        draw.text(
            (x, y),
            line,
            font=selected_font,
            fill="white",
            stroke_width=3,
            stroke_fill="black"
        )

        y += 105

    draw.text(
        (95, 1660),
        "GTA VI COMMUNITY UPDATE",
        font=font(38),
        fill=(255, 220, 90)
    )

    canvas.save(img)

    (OUTPUT / f"gta_vi_{stamp}.txt").write_text(
        f"SOURCE: {item.get('url', '')}\n"
        f"TITLE: {title}\n\n"
        f"SCRIPT:\n{script}",
        encoding="utf-8"
    )

    audio = asyncio.run(voice(script, audio_mp3))

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loop", "1",
            "-i", str(img),
            "-i", str(audio),
            "-vf", "scale=1080:1920,format=yuv420p",
            "-c:v", "libx264",
            "-tune", "stillimage",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            "-movflags", "+faststart",
            str(video)
        ],
        check=True
    )

    print("Short de prueba creado:", video)


if __name__ == "__main__":
    main()
