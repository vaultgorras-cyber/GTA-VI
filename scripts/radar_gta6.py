
import json
import os
from datetime import datetime, timezone
from pathlib import Path

# GTA VI Trend Radar
# Primera fase: preparar el registro de temas para investigar.

PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

RADAR_FILE = DATA_DIR / "radar_history.json"

TOPICS = [
    "GTA 6",
    "GTA VI news",
    "GTA 6 gameplay",
    "GTA 6 trailer",
    "GTA 6 release date",
    "GTA 6 Lucia",
    "GTA 6 Jason",
    "GTA 6 Vice City",
    "Rockstar Games GTA 6",
]

def load_history():
    if RADAR_FILE.exists():
        try:
            return json.loads(RADAR_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
    return []

def save_history(history):
    RADAR_FILE.parent.mkdir(parents=True, exist_ok=True)
    RADAR_FILE.write_text(
        json.dumps(history, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

def main():
    history = load_history()

    run = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "topics_to_research": TOPICS,
        "status": "initialized",
    }

    history.append(run)
    save_history(history)

    print("GTA VI RADAR ejecutado correctamente.")
    print(f"Temas preparados: {len(TOPICS)}")
    print(f"Historial de comprobaciones: {len(history)}")

if __name__ == "__main__":
    main()
