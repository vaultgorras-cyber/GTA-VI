
import json
import os
import re
from datetime import datetime, timezone

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from config import OUTPUT, DATA


# ============================================================
# CONFIGURACIÓN
# ============================================================

UPLOAD_LOG = DATA / "uploaded.json"

PRIVACY_STATUS = "private"

YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload"
]


def log(*args):
    print("[YOUTUBE UPLOAD]", *args, flush=True)


# ============================================================
# HISTORIAL DE SUBIDAS
# ============================================================

def load_upload_history():
    if not UPLOAD_LOG.exists():
        return []

    try:
        data = json.loads(
            UPLOAD_LOG.read_text(encoding="utf-8")
        )

        if isinstance(data, list):
            return data

        return []

    except Exception as error:
        log("Could not read upload history:", error)
        return []


def save_upload_history(entries):
    temporary = UPLOAD_LOG.with_suffix(".tmp")

    temporary.write_text(
        json.dumps(
            entries[-500:],
            ensure_ascii=False,
            indent=2
        ),
        encoding="utf-8"
    )

    temporary.replace(UPLOAD_LOG)


# ============================================================
# METADATOS DEL VÍDEO
# ============================================================

def load_video_report(video):
    stamp = video.stem.replace("gta_vi_", "")
    report_path = OUTPUT / f"gta_vi_{stamp}_report.json"

    if not report_path.exists():
        return {}

    try:
        return json.loads(
            report_path.read_text(encoding="utf-8")
        )

    except Exception as error:
        log("Report could not be read:", error)
        return {}


def clean_title(value):
    title = re.sub(r"\s+", " ", str(value)).strip()

    if not title:
        title = "GTA VI News and Community Update"

    return title[:100]


def make_description(report):
    source = str(report.get("source", "")).strip()

    description = (
        "GTA VI news, discoveries and community analysis.\n\n"
        "This video discusses information about Grand Theft Auto VI, "
        "separating confirmed information from rumours and speculation.\n\n"
        "Subscribe for more GTA VI updates.\n"
    )

    if source.startswith(("https://", "http://")):
        description += f"\nSource:\n{source}\n"

    image_sources = report.get("images", [])

    if image_sources:
        description += "\nImage credits and licenses:\n"

        for image in image_sources:
            image_source = image.get("source", "")
            author = image.get("author", "Unknown")
            license_name = image.get("license", "Unspecified")

            if image_source:
                description += (
                    f"- {author} | {license_name} | "
                    f"{image_source}\n"
                )

    description += "\n#GTA6 #GTAVI #RockstarGames"

    return description[:5000]


# ============================================================
# CONEXIÓN SEGURA CON YOUTUBE
# ============================================================

def connect_youtube():
    client_id = os.getenv("YT_CLIENT_ID", "").strip()
    client_secret = os.getenv("YT_CLIENT_SECRET", "").strip()
    refresh_token = os.getenv("YT_REFRESH_TOKEN", "").strip()

    if not all((client_id, client_secret, refresh_token)):
        raise RuntimeError(
            "Faltan secretos OAuth de YouTube en GitHub."
        )

    credentials = Credentials(
        None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=YOUTUBE_SCOPES
    )

    credentials.refresh(Request())

    return build(
        "youtube",
        "v3",
        credentials=credentials
    )


# ============================================================
# SELECCIÓN DEL VÍDEO
# ============================================================

def find_pending_video(entries):
    uploaded_files = {
        entry.get("file")
        for entry in entries
        if entry.get("id")
    }

    videos = sorted(
        OUTPUT.glob("gta_vi_*.mp4"),
        key=lambda path: path.stat().st_mtime,
        reverse=True
    )

    for video in videos:
        if video.name not in uploaded_files:
            if video.stat().st_size > 100000:
                return video

    return None


# ============================================================
# SUBIDA PRIVADA
# ============================================================

def upload_video(youtube, video):
    report = load_video_report(video)

    title = clean_title(
        report.get("title", video.stem.replace("_", " "))
    )

    description = make_description(report)

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": [
                "GTA 6",
                "GTA VI",
                "Grand Theft Auto VI",
                "Rockstar Games",
                "Vice City",
                "GTA VI News"
            ],
            "categoryId": "20"
        },
        "status": {
            "privacyStatus": PRIVACY_STATUS,
            "selfDeclaredMadeForKids": False
        }
    }

    # Protección adicional: nunca subir como público.
    if body["status"]["privacyStatus"] != "private":
        raise RuntimeError(
            "Protección activada: se ha bloqueado una subida no privada."
        )

    media = MediaFileUpload(
        str(video),
        mimetype="video/mp4",
        chunksize=8 * 1024 * 1024,
        resumable=True
    )

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media
    )

    response = None

    while response is None:
        status, response = request.next_chunk()

        if status:
            percentage = int(status.progress() * 100)
            log(f"Upload progress: {percentage}%")

    return response


# ============================================================
# MAIN
# ============================================================

def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    DATA.mkdir(parents=True, exist_ok=True)

    entries = load_upload_history()

    video = find_pending_video(entries)

    if video is None:
        log("No new final videos to upload.")
        return

    log("Selected video:", video.name)

    youtube = connect_youtube()

    response = upload_video(youtube, video)

    video_id = response.get("id")

    if not video_id:
        raise RuntimeError(
            "YouTube did not return a video ID."
        )

    entry = {
        "id": video_id,
        "file": video.name,
        "title": load_video_report(video).get(
            "title",
            video.stem
        ),
        "privacy_status": "private",
        "at": datetime.now(timezone.utc).isoformat()
    }

    entries.append(entry)

    save_upload_history(entries)

    log("Upload successful.")
    log("Video ID:", video_id)
    log("Privacy: PRIVATE")
    log(
        "Review URL:",
        f"https://www.youtube.com/watch?v={video_id}"
    )


if __name__ == "__main__":
    main()
