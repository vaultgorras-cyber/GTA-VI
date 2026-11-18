import os
from pathlib import Path

# ============================================================
# RUTAS PRINCIPALES DEL PROYECTO
# ============================================================

ROOT = Path(__file__).resolve().parent.parent

DATA = ROOT / "data"
OUTPUT = ROOT / "output"
SCRIPTS = ROOT / "scripts"

ASSETS = ROOT / "assets"
GAMEPLAY_DIR = ASSETS / "gameplay"
IMAGES_DIR = ASSETS / "images"
MUSIC_DIR = ASSETS / "music"

for folder in (
    DATA,
    OUTPUT,
    ASSETS,
    GAMEPLAY_DIR,
    IMAGES_DIR,
    MUSIC_DIR,
):
    folder.mkdir(parents=True, exist_ok=True)


# ============================================================
# ARCHIVOS DE DATOS E HISTORIAL
# ============================================================

CANDIDATES_FILE = DATA / "candidates.json"
SEEN_FILE = DATA / "seen.json"
PUBLISHED_FILE = DATA / "published.json"
HISTORY_FILE = DATA / "history.json"

# No sustituir ni borrar los archivos existentes.
# El radar y el generador pueden seguir utilizando sus rutas actuales.


# ============================================================
# CONFIGURACIÓN DE YOUTUBE Y OPENROUTER
# ============================================================

YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY", "").strip()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()

OPENROUTER_MODEL = os.getenv(
    "OPENROUTER_MODEL",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
).strip()


# ============================================================
# FUENTES RSS PARA EL RADAR GTA VI
# ============================================================

DEFAULT_RSS_URLS = [
    "https://www.ign.com/rss/v2/articles/feed",
    "https://feeds.feedburner.com/ign/games-all",
    "https://feeds.feedburner.com/ign/news",
    "https://www.pcgamer.com/feeds.xml",
    "https://www.rockpapershotgun.com/feed",
    "https://www.theverge.com/rss/games/index.xml",
]

rss_environment = os.getenv("NEWS_RSS_URLS", "").strip()

if rss_environment:
    RSS_URLS = [
        url.strip()
        for url in rss_environment.split(",")
        if url.strip()
    ]
else:
    RSS_URLS = DEFAULT_RSS_URLS


# ============================================================
# CONFIGURACIÓN DE LOS VÍDEOS
# ============================================================

VIDEO_WIDTH = 1920
VIDEO_HEIGHT = 1080
VIDEO_FPS = 30

VIDEO_MIN_SECONDS = 240
VIDEO_MAX_SECONDS = 420

VIDEO_MIN_WORDS = 600
VIDEO_MAX_WORDS = 850

DAILY_VIDEO_TARGET = 3

VIDEO_LANGUAGE = "en-US"
VIDEO_VOICE = os.getenv(
    "VIDEO_VOICE",
    "en-US-ChristopherNeural",
).strip()

VIDEO_FORMAT = "mp4"


# ============================================================
# SUBTÍTULOS
# ============================================================

SUBTITLES_ENABLED = True

SUBTITLE_WORD_BY_WORD = True

SUBTITLE_FONT_SIZE = 58
SUBTITLE_FONT = "Arial"

SUBTITLE_COLOR = "white"
SUBTITLE_OUTLINE_COLOR = "black"
SUBTITLE_OUTLINE_WIDTH = 3

SUBTITLE_POSITION = "bottom"


# ============================================================
# FONDOS DE GAMEPLAY
# ============================================================

# Estas URL se guardan como referencias.
# No se descargan automáticamente: comprueba antes que tienes
# permiso para reutilizar los vídeos y el audio.

DEFAULT_GAMEPLAY_URLS = [
    "https://youtu.be/ARwju5Gyk64",
    "https://youtube.com/playlist?list=PLdxE72LlkFocq2kZMWPppfZMrqOtGtU_a",
]

GAMEPLAY_URLS_FILE = DATA / "gameplay_urls.txt"

GAMEPLAY_LOCAL_DIR = GAMEPLAY_DIR

GAMEPLAY_LOOP = True

# El generador debe utilizar vídeos locales autorizados
# que estén dentro de assets/gameplay.


# ============================================================
# IMÁGENES DE APOYO
# ============================================================

USE_SUPPORT_IMAGES = True

IMAGE_ASSETS_DIR = IMAGES_DIR

IMAGE_LICENSE_CHECK = True

# Las imágenes se intercalan como escenas breves.
# No deben ocupar permanentemente la pantalla.


# ============================================================
# MÚSICA DE FONDO
# ============================================================

USE_BACKGROUND_MUSIC = True

BACKGROUND_MUSIC_DIR = MUSIC_DIR

BACKGROUND_MUSIC_VOLUME = 0.10

# Utiliza únicamente música propia o con licencia compatible.


# ============================================================
# RADAR Y CONTROL DE REPETICIONES
# ============================================================

RADAR_INTERVAL_MINUTES = 15

AVOID_DUPLICATE_TOPICS = True

TOPIC_HISTORY_FILE = PUBLISHED_FILE

MAX_CANDIDATES = 100

MIN_TOPIC_RELEVANCE = 1


# ============================================================
# SUBIDA A YOUTUBE
# ============================================================

ENABLE_PRIVATE_UPLOAD = (
    os.getenv("ENABLE_PRIVATE_UPLOAD", "false").lower() == "true"
)

YOUTUBE_PRIVACY_STATUS = "private"

# La automatización no debe publicar vídeos en público.
YOUTUBE_PUBLIC_UPLOAD = False


# ============================================================
# REGISTRO DE CONFIGURACIÓN
# ============================================================

print("GTA VI configuration loaded")
print("RSS sources configured:", len(RSS_URLS))
print("Video resolution:", f"{VIDEO_WIDTH}x{VIDEO_HEIGHT}")
print("Daily video target:", DAILY_VIDEO_TARGET)
print("Radar interval:", RADAR_INTERVAL_MINUTES, "minutes")
print("Private upload enabled:", ENABLE_PRIVATE_UPLOAD)
