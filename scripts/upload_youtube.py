
import json
import os
from datetime import datetime, timezone

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from config import OUTPUT, DATA


def main():
    cid = os.getenv("YT_CLIENT_ID", "")
    secret = os.getenv("YT_CLIENT_SECRET", "")
    refresh = os.getenv("YT_REFRESH_TOKEN", "")

    if not all([cid, secret, refresh]):
        raise RuntimeError("Faltan secretos OAuth de YouTube.")

    log = DATA / "uploaded.json"

    try:
        entries = json.loads(log.read_text(encoding="utf-8"))
    except Exception:
        entries = []

    uploaded_files = {entry.get("file") for entry in entries}

    videos = sorted(
        OUTPUT.glob("*.mp4"),
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )

    pending = [p for p in videos if p.name not in uploaded_files]

    if not pending:
        print("No hay vídeos nuevos para subir.")
        return

    p = pending[0]

    creds = Credentials(
        None,
        refresh_token=refresh,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=cid,
        client_secret=secret,
        scopes=["https://www.googleapis.com/auth/youtube.upload"]
    )

    creds.refresh(Request())
    yt = build("youtube", "v3", credentials=creds)

    title = "GTA VI Explained: Latest Community Update"

    description = (
        "An original GTA VI news and community analysis video. "
        "We separate confirmed information from rumours and speculation. "
        "\n\nSubscribe for more Grand Theft Auto VI updates."
        "\n\n#GTA6 #GTAVI #RockstarGames"
    )

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": [
                "GTA 6",
                "GTA VI",
                "Grand Theft Auto VI",
                "Rockstar Games",
                "Vice City"
            ],
            "categoryId": "20"
        },
        "status": {
            "privacyStatus": "private",
            "selfDeclaredMadeForKids": False
        }
    }

    media = MediaFileUpload(
        str(p),
        mimetype="video/mp4",
        chunksize=8 * 1024 * 1024,
        resumable=True
    )

    request = yt.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media
    )

    response = None

    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"Subida: {int(status.progress() * 100)}%")

    entries.append({
        "id": response["id"],
        "file": p.name,
        "at": datetime.now(timezone.utc).isoformat()
    })

    log.write_text(
        json.dumps(entries[-500:], indent=2),
        encoding="utf-8"
    )

    print("Vídeo subido como PRIVADO:", response["id"])


if __name__ == "__main__":
    main()
