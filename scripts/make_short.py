import os
import re
import json
import time
import math
import html
import asyncio
import subprocess
import urllib.request
import urllib.parse

from pathlib import Path
from datetime import datetime, timezone
from html.parser import HTMLParser

from PIL import Image, ImageDraw, ImageFont
import edge_tts

from config import DATA, OUTPUT


# ============================================================
# CONFIGURATION
# ============================================================

WIDTH = 1920
HEIGHT = 1080

MIN_AUDIO = 240
MAX_AUDIO = 420

MIN_WORDS = 600
MAX_WORDS = 850

MODEL = os.getenv(
    "OPENROUTER_MODEL",
    "nvidia/nemotron-3-ultra-550b-a55b:free"
)

OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
YOUTUBE_KEY = os.getenv("YOUTUBE_API_KEY", "").strip()

USER_AGENT = "GTA-VI-404-Automation/1.0"

FONT_PATH = (
    "/usr/share/fonts/truetype/dejavu/"
    "DejaVuSans-Bold.ttf"
)

GAMEPLAY_SEARCHES = [
    "GTA 5 racing gameplay Creative Commons",
    "GTA 5 driving gameplay Creative Commons",
    "GTA 5 police chase gameplay Creative Commons",
    "GTA 6 gameplay Creative Commons",
    "Grand Theft Auto gameplay Creative Commons"
]


def log(*args):
    print("[GTA VI]", *args, flush=True)


def get_json(url, headers=None):
    h = {"User-Agent": USER_AGENT}

    if headers:
        h.update(headers)

    request = urllib.request.Request(url, headers=h)

    with urllib.request.urlopen(request, timeout=40) as response:
        return json.loads(response.read().decode("utf-8"))


# ============================================================
# NEWS SELECTION
# ============================================================

def load_news():
    path = DATA / "candidates.json"

    if not path.exists():
        return []

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("items", [])

    except Exception as error:
        log("News loading error:", error)
        return []


def choose_topic(items):
    if not items:
        return None

    gta_pattern = re.compile(
        r"\b(?:GTA\s*(?:VI|6)|Grand Theft Auto\s*(?:VI|6))\b",
        re.IGNORECASE
    )

    non_english_markers = re.compile(
        r"\b(primeiro|primeira|contas|banindo|cancelado|nova zel[aâ]ndia|"
        r"not[ií]cias|jogos|lan[cç]amento|vazamento|vazou|"
        r"últimas|último|última|espa[nñ]ol|fran[cç]ais|"
        r"portugu[eê]s|alem[aã]o)\b",
        re.IGNORECASE
    )

    valid = []

    for item in items:
        title = html.unescape(str(item.get("title", ""))).strip()
        summary = html.unescape(str(item.get("summary", ""))).strip()

        if not gta_pattern.search(title):
            log("Rejected topic without clear GTA VI title:", title[:140])
            continue

        if title.count("|") >= 1 or non_english_markers.search(title):
            log("Rejected mixed or non-English topic:", title[:140])
            continue

        if len(title.split()) < 4:
            log("Rejected short topic title:", title)
            continue

        item["_clean_title"] = title
        item["_clean_summary"] = summary
        valid.append(item)

    if not valid:
        log("No suitable English GTA VI topic. No video will be generated.")
        return None

    def ranking(item):
        trend = (
            item.get("is_trending")
            or item.get("priority") == "trend"
        )

        score = int(
            item.get("trend_score", item.get("score", 0)) or 0
        )

        date = str(
            item.get("published", item.get("published_at", ""))
        )

        return int(bool(trend)), score, date

    return sorted(valid, key=ranking, reverse=True)[0]


# ============================================================
# ARTICLE READING
# ============================================================

class ArticleParser(HTMLParser):

    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag.lower() in ("script", "style", "noscript"):
            self.skip += 1

    def handle_endtag(self, tag):
        if tag.lower() in ("script", "style", "noscript") and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            text = " ".join(data.split())
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

        with urllib.request.urlopen(request, timeout=25) as response:
            raw = response.read(1000000).decode(
                "utf-8", errors="replace"
            )

        parser = ArticleParser()
        parser.feed(raw)

        return " ".join(parser.parts)[:9000]

    except Exception as error:
        log("Article unavailable:", error)
        return ""


# ============================================================
# AUTOMATIC SCRIPT
# ============================================================

def generate_script(item, article):

    if not OPENROUTER_KEY:
        raise RuntimeError("OPENROUTER_API_KEY is missing.")

    title = item.get("_clean_title") or html.unescape(
        str(item.get("title", "GTA VI News"))
    )

    summary = item.get("_clean_summary") or html.unescape(
        str(item.get("summary", ""))
    )

    source = item.get("url", "")

    base_prompt = f"""
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
- Write 650 to 800 spoken words. This limit is mandatory.
- Aim for approximately five minutes of narration.
- Strong but accurate opening.
- Explain the news and why it matters to GTA players.
- Clearly distinguish confirmed information from rumours.
- Never invent facts, dates, quotes or announcements.
- Explain what is still unknown.
- Natural, engaging American English.
- No headings, bullets, markdown, word count or notes.
- Return only the spoken narration.
"""

    prompt = base_prompt

    for attempt in range(1, 5):
        payload = {
            "model": MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a concise professional American gaming journalist. "
                        "Follow the requested word limit exactly. Never add filler "
                        "or invent facts."
                    )
                },
                {"role": "user", "content": prompt}
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
                result = json.loads(response.read().decode("utf-8"))

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
                prompt = f"""
Rewrite the narration below into 700 to 780 words. This is a strict maximum-length
task. Keep the key confirmed facts, explain why they matter to GTA players, and
separate rumours from confirmed information. Remove repetition, filler and
unrelated details. Do not add facts. Return only the narration, with no headings.

NARRATION TO SHORTEN:
{script}
"""
            else:
                prompt = f"""
Expand the narration below to 650 to 750 words without adding unsupported facts.
Add useful explanation and context only when supported by the source material.
Keep natural American English. Return only the narration, with no headings.

NARRATION TO EXPAND:
{script}
"""

        except Exception as error:
            log("OpenRouter error:", error)
            prompt = base_prompt

        time.sleep(3)

    raise RuntimeError(
        "The AI did not produce a narration between 600 and 850 words after "
        "four attempts. No video was created."
    )
