#!/usr/bin/env python3
"""
Social Media Content Pipeline
Generates viral short-form videos for TikTok / Reels / Shorts.

Modes:
  --mode reddit     Pull top stories from Reddit (AITA, TIFU, etc.)
  --mode news       Trending news stories via Tavily
  --mode history    "On this day in history" via Tavily
  --mode spiritual  Bhagavad Gita verse + meaning via Tavily

Stack:
  - Reddit API (PRAW)     → reddit mode
  - Tavily                → news / history / spiritual modes
  - Local template writer → default spiritual scriptwriting
  - Anthropic Claude      → optional scriptwriting upgrade
  - macOS say             → default local test narration
  - ElevenLabs            → optional production text-to-speech narration
  - Pexels                → royalty-free background footage (CC0)
  - FFmpeg                → compose final 9:16 vertical video
"""

import os
import re
import json
import time
import math
import random
import textwrap
import subprocess
import sys
import shutil
from datetime import datetime
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv():
        return False

load_dotenv()

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
REDDIT_CLIENT_ID     = os.getenv("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET", "")
REDDIT_USER_AGENT    = os.getenv("REDDIT_USER_AGENT", "ContentBot/1.0")

ELEVENLABS_API_KEY  = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")  # Rachel
TTS_ENGINE          = os.getenv("TTS_ENGINE", "local").strip().lower()
LOCAL_TTS_VOICE     = os.getenv("LOCAL_TTS_VOICE", "Samantha")

PEXELS_API_KEY    = os.getenv("PEXELS_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
TAVILY_API_KEY    = os.getenv("TAVILY_API_KEY", "")
ANTHROPIC_MODEL   = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-8")
SCRIPT_ENGINE     = os.getenv("SCRIPT_ENGINE", "template").strip().lower()

OUTPUT_DIR = Path("output")
TEMP_DIR   = Path("temp")

DEFAULT_SUBREDDITS = ["AITA", "tifu", "confessions", "TrueOffMyChest"]
DEFAULT_SPIRITUAL_TOPICS = [
    "karma",
    "dharma",
    "detachment",
    "courage",
    "discipline",
    "inner peace",
    "devotion",
    "self control",
    "purpose",
    "fear",
    "grief",
    "service",
]

VIDEO_W, VIDEO_H, VIDEO_FPS = 1080, 1920, 30
WPS = 2.8   # words per second (ElevenLabs pacing)
SPIRITUAL_IMAGE_COUNT = int(os.getenv("SPIRITUAL_IMAGE_COUNT", "8"))

VALID_MODES = ["reddit", "news", "history", "spiritual"]
DEFAULT_MODE = os.getenv("PIPELINE_DEFAULT_MODE", "spiritual")
VALID_SCRIPT_ENGINES = ["template", "anthropic"]
VALID_TTS_ENGINES = ["local", "elevenlabs"]

SPIRITUAL_VISUAL_QUERIES = [
    "ancient indian temple",
    "hindu god statue",
    "krishna temple india",
    "shiva statue india",
    "vishnu temple india",
    "rajasthan palace",
    "maharaja palace india",
    "hampi temple india",
    "khajuraho temple sculpture",
    "varanasi temple",
    "indian temple sculpture",
    "golden temple india",
]


# ─────────────────────────────────────────────
# UTILITIES
# ─────────────────────────────────────────────

def is_configured(value: str) -> bool:
    if not value:
        return False
    lowered = value.strip().lower()
    return not (
        lowered.startswith("your_")
        or lowered in {"changeme", "replace_me", "todo"}
    )


def uses_anthropic(mode: str) -> bool:
    """Anthropic is optional for spiritual mode, required for legacy modes."""
    return SCRIPT_ENGINE == "anthropic" or mode != "spiritual"


def uses_elevenlabs() -> bool:
    return TTS_ENGINE == "elevenlabs"


def check_deps(mode: str):
    # FFmpeg
    try:
        run_ffmpeg(["-version"], capture_output=True, check=True)
    except (FileNotFoundError, RuntimeError, subprocess.CalledProcessError):
        print("❌  FFmpeg not found. Install ffmpeg or run: python3 -m pip install -r requirements.txt")
        sys.exit(1)

    missing = []
    if uses_elevenlabs() and not is_configured(ELEVENLABS_API_KEY):
        missing.append("ELEVENLABS_API_KEY")
    if not is_configured(PEXELS_API_KEY):     missing.append("PEXELS_API_KEY")
    if uses_anthropic(mode) and not is_configured(ANTHROPIC_API_KEY):
        missing.append("ANTHROPIC_API_KEY")
    if mode == "reddit" and (not is_configured(REDDIT_CLIENT_ID) or not is_configured(REDDIT_CLIENT_SECRET)):
        missing.append("REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET")
    if mode in ("news", "history", "spiritual") and not is_configured(TAVILY_API_KEY):
        missing.append("TAVILY_API_KEY")
    if missing:
        print("❌  Missing environment variables in .env:")
        for m in missing:
            print(f"    • {m}")
        print("\n   Copy .env.example -> .env and fill in the values.")
        sys.exit(1)
    if SCRIPT_ENGINE not in VALID_SCRIPT_ENGINES:
        print(f"❌  Invalid SCRIPT_ENGINE={SCRIPT_ENGINE}. Choose from: {VALID_SCRIPT_ENGINES}")
        sys.exit(1)
    if TTS_ENGINE not in VALID_TTS_ENGINES:
        print(f"❌  Invalid TTS_ENGINE={TTS_ENGINE}. Choose from: {VALID_TTS_ENGINES}")
        sys.exit(1)
    if TTS_ENGINE == "local" and not shutil.which("say"):
        print("❌  Local TTS requires macOS 'say'. Set TTS_ENGINE=elevenlabs to use ElevenLabs.")
        sys.exit(1)


def require_package(import_name: str, package_name: str = None):
    try:
        return __import__(import_name)
    except ImportError as exc:
        name = package_name or import_name
        raise RuntimeError(
            f"Missing Python package '{name}'. Install dependencies with: "
            "python3 -m pip install -r requirements.txt"
        ) from exc


def ffmpeg_exe() -> str:
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg
    try:
        imageio_ffmpeg = require_package("imageio_ffmpeg", "imageio-ffmpeg")
        return imageio_ffmpeg.get_ffmpeg_exe()
    except RuntimeError:
        return ""


def run_ffmpeg(args: list, **kwargs):
    exe = ffmpeg_exe()
    if not exe:
        raise RuntimeError(
            "FFmpeg not found. Install ffmpeg or install Python dependencies "
            "with imageio-ffmpeg included."
        )
    return subprocess.run([exe, *args], **kwargs)


def get_audio_duration(path: Path) -> float:
    result = run_ffmpeg(["-i", str(path), "-f", "null", "-"], capture_output=True, text=True)
    combined = f"{result.stdout}\n{result.stderr}"
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", combined)
    if not match:
        raise RuntimeError("Could not determine audio duration from FFmpeg output.")
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def seconds_to_srt_time(s: float) -> str:
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    sec = s % 60
    return f"{h:02d}:{m:02d}:{sec:06.3f}".replace(".", ",")


def caption_chunks(script: str, max_words: int = 6) -> list:
    chunks = []
    sentences = re.split(r'(?<=[.!?])\s+', script.strip())
    for sentence in sentences:
        words = sentence.split()
        for i in range(0, len(words), max_words):
            chunk = " ".join(words[i:i + max_words]).strip()
            if chunk:
                chunks.append(chunk)
    return chunks


def build_srt(script: str, wps: float = WPS) -> str:
    chunks = caption_chunks(script)
    lines = []
    t = 0.0
    for i, chunk in enumerate(chunks, 1):
        words = len(chunk.split())
        dur   = max(1.5, words / wps)
        start = seconds_to_srt_time(t)
        end   = seconds_to_srt_time(t + dur)
        wrapped = "\n".join(textwrap.wrap(chunk, width=20))
        lines.append(f"{i}\n{start} --> {end}\n{wrapped}\n")
        t += dur + 0.1
    return "\n".join(lines)


def escape_ffmpeg_text(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:")


def hex_color_saturation(hex_color: str) -> float:
    color = str(hex_color or "").strip().lstrip("#")
    if len(color) != 6:
        return 1.0
    try:
        r, g, b = (int(color[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except ValueError:
        return 1.0
    max_c = max(r, g, b)
    min_c = min(r, g, b)
    if max_c == 0:
        return 0.0
    return (max_c - min_c) / max_c


def is_colorful_photo(photo: dict) -> bool:
    """Reject likely black-and-white or very flat images from Pexels."""
    avg_color = photo.get("avg_color")
    if not avg_color:
        return True
    return hex_color_saturation(avg_color) >= 0.10


def spiritual_visual_queries(keywords: list = None) -> list:
    cleaned = [
        str(kw).strip()
        for kw in (keywords or [])
        if str(kw).strip() and str(kw).strip().lower() not in {"nature", "abstract background"}
    ]
    devotional = [*SPIRITUAL_VISUAL_QUERIES, *cleaned]
    seen = set()
    unique = []
    for query in devotional:
        key = query.lower()
        if key not in seen:
            unique.append(query)
            seen.add(key)
    return unique


def daily_spiritual_topic(today: datetime = None) -> str:
    """Pick a stable rotating topic for unattended daily spiritual runs."""
    today = today or datetime.now()
    index = today.timetuple().tm_yday % len(DEFAULT_SPIRITUAL_TOPICS)
    return DEFAULT_SPIRITUAL_TOPICS[index]


def normalize_hashtags(hashtags: list) -> list:
    normalized = []
    for tag in hashtags or []:
        clean = re.sub(r"[^A-Za-z0-9_]", "", str(tag).strip().lstrip("#"))
        if clean:
            normalized.append(f"#{clean}")
    defaults = ["#BhagavadGita", "#Spirituality", "#Mindfulness", "#Wisdom", "#Shorts"]
    for tag in defaults:
        if tag not in normalized:
            normalized.append(tag)
    return normalized[:8]


def title_case_topic(topic: str) -> str:
    return " ".join(word.capitalize() for word in str(topic or "inner peace").split())


def write_spiritual_template_script(content: dict) -> dict:
    """Create a Gita reflection without an LLM or Anthropic API key."""
    topic = content.get("topic") or os.getenv("SPIRITUAL_TOPIC") or "inner peace"
    topic_title = title_case_topic(topic)
    title = f"Gita Wisdom for {topic_title}"[:60]
    hook = f"When {topic} feels hard, the Gita does not ask you to run from life."
    script = (
        f"{hook} It asks you to meet life with a steadier mind. "
        "The teaching is simple: offer your action fully, but do not let your peace depend on the result. "
        "That one shift changes everything. You can still work, love, serve, build, and try again, but your heart is no longer dragged around by praise, fear, or disappointment. "
        f"If your lesson today is {topic}, pause before reacting. Ask what duty is in front of you. Ask what response would make you cleaner inside, not louder outside. "
        "The Gita keeps bringing us back to this quiet strength: do the right thing with sincerity, release what you cannot control, and return to the self that watches all of it. "
        "Maybe that is the real practice today: not escaping the world, but moving through it without losing yourself."
    )
    return {
        "video_title": title,
        "script": script,
        "hook": hook,
        "search_keywords": [
            "ancient indian temple",
            "hindu god statue",
            "krishna temple india",
            "rajasthan palace",
            "indian temple sculpture",
        ],
        "hashtags": ["#BhagavadGita", "#GitaWisdom", "#Spirituality", "#Mindfulness", "#Shorts"],
        "script_engine": "template",
    }


def build_upload_metadata(content: dict, scripted: dict, video_path: Path, duration: float) -> dict:
    """Create platform-ready metadata for TikTok, Reels, and YouTube Shorts."""
    hashtags = normalize_hashtags(scripted.get("hashtags", []))
    title = str(scripted.get("video_title") or content.get("title") or "Bhagavad Gita Reflection")[:90]
    hook = str(scripted.get("hook") or scripted.get("script", "").split(".")[0]).strip()
    caption = f"{title}\n\n{hook}\n\n{' '.join(hashtags)}"
    description = (
        f"{title}\n\n"
        f"{scripted.get('script', '').strip()}\n\n"
        f"Source reference: {content.get('source', 'Tavily research')}\n\n"
        f"{' '.join(hashtags)}"
    )
    alt_text = (
        "Vertical short-form video with peaceful background footage and narrated "
        "Bhagavad Gita reflection captions."
    )
    return {
        "publish_status": "ready_to_upload",
        "content_lane": "gita_spiritual",
        "mode": content.get("mode"),
        "source": content.get("source"),
        "video_file": str(video_path),
        "duration_seconds": round(duration, 2),
        "title": title,
        "caption": caption,
        "description": description,
        "hashtags": hashtags,
        "alt_text": alt_text,
        "platforms": {
            "tiktok": {
                "caption": caption[:2200],
                "hashtags": hashtags,
                "privacy": "draft",
            },
            "instagram_reels": {
                "caption": caption[:2200],
                "hashtags": hashtags,
                "share_to_feed": True,
            },
            "youtube_shorts": {
                "title": title[:100],
                "description": description[:5000],
                "tags": [tag.lstrip("#") for tag in hashtags],
                "category": "Education",
                "made_for_kids": False,
            },
        },
    }


def system_font() -> str:
    candidates = [
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for p in candidates:
        if Path(p).exists():
            return p
    return ""


# ─────────────────────────────────────────────
# CONTENT SOURCES
# ─────────────────────────────────────────────

def fetch_reddit_story(subreddit: str = None, time_filter: str = "week") -> dict:
    """Mode: reddit — pull a top post from a subreddit."""
    praw = require_package("praw")
    if not subreddit:
        subreddit = random.choice(DEFAULT_SUBREDDITS)

    reddit = praw.Reddit(
        client_id=REDDIT_CLIENT_ID,
        client_secret=REDDIT_CLIENT_SECRET,
        user_agent=REDDIT_USER_AGENT
    )
    posts = list(reddit.subreddit(subreddit).top(time_filter=time_filter, limit=50))
    suitable = [
        p for p in posts
        if 500 <= len(p.selftext) <= 3500
        and not p.stickied
        and p.selftext not in ("[removed]", "[deleted]", "")
    ]
    if not suitable:
        raise ValueError(f"No suitable posts in r/{subreddit}")

    post = random.choice(suitable[:8])
    return {
        "mode": "reddit",
        "title": post.title,
        "body": post.selftext,
        "source": f"r/{subreddit}",
    }


def fetch_news_story(topic: str = None) -> dict:
    """Mode: news — find a trending story via Tavily."""
    tavily_module = require_package("tavily", "tavily-python")
    TavilyClient = tavily_module.TavilyClient
    client = TavilyClient(api_key=TAVILY_API_KEY)
    query = f"trending news story today {topic}" if topic else "most shocking surprising news story today"
    results = client.search(query, search_depth="advanced", max_results=5)

    if not results.get("results"):
        raise ValueError("No news results from Tavily.")

    # Pick the most content-rich result
    best = max(results["results"], key=lambda r: len(r.get("content", "")))
    return {
        "mode": "news",
        "title": best["title"],
        "body": best["content"],
        "source": best["url"],
    }


def fetch_history_story() -> dict:
    """Mode: history — find an 'on this day' historical event via Tavily."""
    tavily_module = require_package("tavily", "tavily-python")
    TavilyClient = tavily_module.TavilyClient
    client = TavilyClient(api_key=TAVILY_API_KEY)
    today = datetime.now().strftime("%B %d")
    results = client.search(
        f"most incredible historical event that happened on {today} in history",
        search_depth="advanced", max_results=5
    )

    if not results.get("results"):
        raise ValueError("No history results from Tavily.")

    best = max(results["results"], key=lambda r: len(r.get("content", "")))
    return {
        "mode": "history",
        "title": best["title"],
        "body": best["content"],
        "source": best["url"],
    }


def fetch_spiritual_verse(topic: str = None) -> dict:
    """Mode: spiritual — find a Bhagavad Gita verse + meaning via Tavily."""
    tavily_module = require_package("tavily", "tavily-python")
    TavilyClient = tavily_module.TavilyClient
    client = TavilyClient(api_key=TAVILY_API_KEY)
    topic = topic or os.getenv("SPIRITUAL_TOPIC") or daily_spiritual_topic()
    query = (
        f"Bhagavad Gita verse about {topic} full Sanskrit translation "
        "meaning explanation life lesson"
    )
    results = client.search(query, search_depth="advanced", max_results=5)

    if not results.get("results"):
        raise ValueError("No results from Tavily for spiritual content.")

    best = max(results["results"], key=lambda r: len(r.get("content", "")))
    return {
        "mode": "spiritual",
        "title": best["title"],
        "body": best["content"],
        "source": best["url"],
        "topic": topic,
    }


# ─────────────────────────────────────────────
# SCRIPTWRITING (Claude)
# ─────────────────────────────────────────────

MODE_PROMPTS = {
    "reddit": """You are a viral short-form video scriptwriter.

Transform the Reddit post below into an original, engaging video script.

RULES:
1. Do NOT copy any sentence verbatim — rewrite completely in your own voice.
2. Replace all usernames, specific locations, and identifying details with generic/fictional ones.
3. Start with a strong hook (first sentence must stop the scroll).
4. Target 150–200 words — roughly 60–75 seconds.
5. First-person perspective. End with an emotional punch or question that invites comments.
6. Category: personal story / relationship / workplace / family.

Background video search keywords should be lifestyle/people/city related.""",

    "news": """You are a viral short-form news narrator.

Turn this news story into a punchy, engaging video script.

RULES:
1. Stick to verifiable facts — do not invent or embellish.
2. Start with a shocking hook: "You won't believe what just happened..."
3. Target 150–180 words — roughly 60–70 seconds.
4. Neutral, journalistic tone but conversational. End with a thought-provoking question.
5. Category: news / current events.

Background video keywords should match the story's topic.""",

    "history": """You are a short-form history narrator.

Turn this historical event into a gripping video script.

RULES:
1. Stick to historical facts only.
2. Hook: start with the most dramatic or surprising element.
3. Target 150–180 words — roughly 60–70 seconds.
4. Dramatic but accurate. End with why this still matters today.
5. Category: history.

Background video keywords should match the era/topic (e.g., 'ancient ruins', 'war archive', 'space').""",

    "spiritual": """You are a spiritual content creator for short-form video.

Turn this Bhagavad Gita verse/teaching into a deeply moving video script.

RULES:
1. Open with the Sanskrit verse or a key line, then explain its meaning.
2. Connect the teaching to a modern, relatable life situation.
3. Target 150–180 words — roughly 60–70 seconds.
4. Calm, reverent, inspiring tone. End with a reflection question for the viewer.
5. Category: spirituality / wisdom / mindfulness.

Background video keywords should be nature/meditation/peaceful (e.g., 'sunrise nature', 'meditation', 'lotus flower', 'temple').""",
}


def write_anthropic_script(content: dict) -> dict:
    """Use Claude to write the final video script from raw source content."""
    anthropic_module = require_package("anthropic")
    Anthropic = anthropic_module.Anthropic
    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    mode   = content["mode"]
    system = MODE_PROMPTS[mode]

    user_msg = f"""Title / Headline: {content['title']}

Source content:
{content['body'][:2500]}

Return ONLY valid JSON (no markdown fences):
{{
  "video_title": "punchy title under 60 chars",
  "script": "full narration script",
  "hook": "the very first sentence",
  "search_keywords": ["keyword1", "keyword2"],
  "hashtags": ["#tag1", "#tag2", "#tag3", "#tag4", "#tag5"]
}}"""

    resp = client.messages.create(
        model=ANTHROPIC_MODEL,
        max_tokens=1024,
        system=system,
        messages=[{"role": "user", "content": user_msg}]
    )

    raw = resp.content[0].text.strip()
    raw = re.sub(r"^```[a-z]*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)
    return json.loads(raw)


def write_script(content: dict) -> dict:
    if content["mode"] == "spiritual" and not uses_anthropic("spiritual"):
        return write_spiritual_template_script(content)
    return write_anthropic_script(content)


# ─────────────────────────────────────────────
# NARRATION
# ─────────────────────────────────────────────

def generate_elevenlabs_narration(script: str, out_dir: Path) -> Path:
    requests = require_package("requests")
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}"
    headers = {
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
        "xi-api-key": ELEVENLABS_API_KEY
    }
    payload = {
        "text": script,
        "model_id": "eleven_monolingual_v1",
        "voice_settings": {
            "stability": 0.50,
            "similarity_boost": 0.75,
            "style": 0.20,
            "use_speaker_boost": True
        }
    }
    resp = requests.post(url, json=payload, headers=headers, timeout=60)
    resp.raise_for_status()
    audio_path = out_dir / "narration.mp3"
    audio_path.write_bytes(resp.content)
    return audio_path


def generate_local_narration(script: str, out_dir: Path) -> Path:
    aiff_path = out_dir / "narration.aiff"
    mp3_path = out_dir / "narration.mp3"
    say_cmd = ["say", "-o", str(aiff_path)]
    if LOCAL_TTS_VOICE:
        say_cmd.extend(["-v", LOCAL_TTS_VOICE])
    say_cmd.append(script)
    subprocess.run(say_cmd, capture_output=True, text=True, check=True)

    result = run_ffmpeg(
        ["-y", "-i", str(aiff_path), "-codec:a", "libmp3lame", "-q:a", "4", str(mp3_path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return aiff_path
    return mp3_path


def generate_narration(script: str, out_dir: Path) -> Path:
    if uses_elevenlabs():
        return generate_elevenlabs_narration(script, out_dir)
    return generate_local_narration(script, out_dir)


# ─────────────────────────────────────────────
# BACKGROUND FOOTAGE (Pexels)
# ─────────────────────────────────────────────

def fetch_background_video(keywords: list, out_dir: Path) -> Path:
    requests = require_package("requests")
    headers   = {"Authorization": PEXELS_API_KEY}
    fallbacks = keywords + ["peaceful nature", "city street", "abstract background"]

    video_url = None
    for kw in fallbacks:
        resp = requests.get(
            "https://api.pexels.com/videos/search",
            headers=headers,
            params={"query": kw, "per_page": 15, "orientation": "portrait"},
            timeout=30
        )
        if resp.status_code != 200:
            continue
        videos = resp.json().get("videos", [])
        if videos:
            vid   = random.choice(videos[:8])
            files = sorted(vid["video_files"], key=lambda f: f.get("width", 0), reverse=True)
            hd    = next((f for f in files if f.get("width", 0) >= 720), files[0])
            video_url = hd["link"]
            break

    if not video_url:
        raise RuntimeError("Could not fetch background video from Pexels. Check your API key.")

    bg_path = out_dir / "background.mp4"
    with requests.get(video_url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(bg_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=65536):
                f.write(chunk)
    return bg_path


def fetch_spiritual_background_images(keywords: list, out_dir: Path, image_count: int = SPIRITUAL_IMAGE_COUNT) -> list:
    requests = require_package("requests")
    headers = {"Authorization": PEXELS_API_KEY}
    image_urls = []
    seen_ids = set()

    for query in spiritual_visual_queries(keywords):
        resp = requests.get(
            "https://api.pexels.com/v1/search",
            headers=headers,
            params={"query": query, "per_page": 12, "orientation": "portrait", "size": "large"},
            timeout=30,
        )
        if resp.status_code != 200:
            continue

        photos = [photo for photo in resp.json().get("photos", []) if is_colorful_photo(photo)]
        random.shuffle(photos)
        for photo in photos[:2]:
            photo_id = photo.get("id")
            if photo_id in seen_ids:
                continue
            src = photo.get("src", {})
            image_url = src.get("large2x") or src.get("portrait") or src.get("large") or src.get("original")
            if not image_url:
                continue
            image_urls.append(image_url)
            seen_ids.add(photo_id)
            if len(image_urls) >= image_count:
                break
        if len(image_urls) >= image_count:
            break

    if not image_urls:
        raise RuntimeError("Could not fetch spiritual background images from Pexels.")

    image_paths = []
    for i, image_url in enumerate(image_urls, 1):
        image_path = out_dir / f"background_{i:02d}.jpg"
        with requests.get(image_url, stream=True, timeout=120) as r:
            r.raise_for_status()
            with open(image_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=65536):
                    f.write(chunk)
        image_paths.append(image_path)
    return image_paths


def build_image_montage(image_paths: list, duration: float, out_dir: Path) -> Path:
    if not image_paths:
        raise ValueError("At least one image is required for a montage.")

    scene_duration = max(3.0, duration / len(image_paths))
    concat_path = out_dir / "montage_inputs.txt"
    concat_lines = []
    for image_path in image_paths:
        concat_lines.append(f"file '{image_path.resolve()}'")
        concat_lines.append(f"duration {scene_duration:.3f}")
    concat_lines.append(f"file '{image_paths[-1].resolve()}'")
    concat_path.write_text("\n".join(concat_lines) + "\n", encoding="utf-8")

    montage_path = out_dir / "background_montage.mp4"
    filter_chain = (
        f"fps={VIDEO_FPS},"
        f"scale={VIDEO_W}:{VIDEO_H}:force_original_aspect_ratio=increase,"
        f"crop={VIDEO_W}:{VIDEO_H},setsar=1,"
        "eq=saturation=1.28:contrast=1.05:brightness=0.015,"
        "format=yuv420p"
    )
    result = run_ffmpeg(
        [
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", str(concat_path),
            "-t", f"{duration + 1:.3f}",
            "-vf", filter_chain,
            "-an",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            str(montage_path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print("FFmpeg montage error:\n", result.stderr[-2000:])
        raise RuntimeError("Image montage generation failed.")
    return montage_path


# ─────────────────────────────────────────────
# VIDEO COMPOSITION (FFmpeg)
# ─────────────────────────────────────────────

def compose_video(bg_path, audio_path, script, title, out_dir) -> Path:
    duration = get_audio_duration(audio_path)
    font     = system_font()

    srt_path = out_dir / "captions.srt"
    srt_path.write_text(build_srt(script), encoding="utf-8")

    safe_title = escape_ffmpeg_text(title[:55])
    font_arg   = f":fontfile='{font}'" if font else ""

    sub_style = (
        "Fontsize=9,Bold=1,PrimaryColour=&H00FCE8C6,OutlineColour=&H70312018,"
        "Outline=0.35,Shadow=0,Alignment=2,MarginV=200"
    )

    escaped_srt_path = escape_ffmpeg_text(srt_path)
    filter_complex = (
        f"[0:v]"
        f"scale={VIDEO_W}:{VIDEO_H}:force_original_aspect_ratio=increase,"
        f"crop={VIDEO_W}:{VIDEO_H},setsar=1,setpts=PTS-STARTPTS,"
        f"eq=saturation=1.18:contrast=1.04:brightness=0.01[bg];"
        f"[bg]drawtext=text='{safe_title}'{font_arg}:fontsize=44:fontcolor=0xF6E7C4:"
        f"x=(w-text_w)/2:y=100:shadowcolor=black@0.55:shadowx=2:shadowy=2:"
        f"line_spacing=6[titled];"
        f"[titled]subtitles='{escaped_srt_path}':original_size={VIDEO_W}x{VIDEO_H}:"
        f"force_style='{sub_style}'[out]"
    )

    out_path = out_dir / "final_video.mp4"
    cmd = [
        "-y",
        "-stream_loop", "-1",
        "-i", str(bg_path),
        "-i", str(audio_path),
        "-t", str(math.ceil(duration) + 1),
        "-filter_complex", filter_complex,
        "-map", "[out]", "-map", "1:a",
        "-r", str(VIDEO_FPS),
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        str(out_path)
    ]

    print("   Running FFmpeg (~30 seconds)...")
    result = run_ffmpeg(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("FFmpeg error:\n", result.stderr[-2000:])
        raise RuntimeError("FFmpeg composition failed.")
    return out_path


# ─────────────────────────────────────────────
# MAIN PIPELINE
# ─────────────────────────────────────────────

def run_pipeline(mode: str = DEFAULT_MODE, topic: str = None, time_filter: str = "week") -> Path:
    check_deps(mode)
    OUTPUT_DIR.mkdir(exist_ok=True)
    job_dir = OUTPUT_DIR / str(int(time.time()))
    job_dir.mkdir(exist_ok=True)

    print(f"\n🎬  Content Pipeline — mode: {mode}\n" + "─" * 40)

    # 1. Fetch source content
    print(f"📖  Fetching content ({mode})...")
    if mode == "reddit":
        content = fetch_reddit_story(subreddit=topic, time_filter=time_filter)
    elif mode == "news":
        content = fetch_news_story(topic=topic)
    elif mode == "history":
        content = fetch_history_story()
    elif mode == "spiritual":
        content = fetch_spiritual_verse(topic=topic)
    else:
        raise ValueError(f"Unknown mode: {mode}. Choose from: {VALID_MODES}")

    print(f"    → {content['title'][:70]}...")

    # 2. Write script
    writer_label = "Anthropic Claude" if uses_anthropic(mode) else "local template writer"
    print(f"✍️   Writing script with {writer_label}...")
    scripted   = write_script(content)
    word_count = len(scripted["script"].split())
    print(f"    → Title:  {scripted['video_title']}")
    print(f"    → Script: {word_count} words (~{round(word_count/WPS)}s narration)")

    # Save metadata
    meta = {
        **content,
        **scripted,
        "script_engine": SCRIPT_ENGINE,
        "tts_engine": TTS_ENGINE,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    (job_dir / "metadata.json").write_text(json.dumps(meta, indent=2))
    (job_dir / "script.txt").write_text(scripted["script"])

    # 3. Narration
    tts_label = "ElevenLabs" if uses_elevenlabs() else "local macOS TTS"
    print(f"🎙️   Generating narration ({tts_label})...")
    audio_path = generate_narration(scripted["script"], job_dir)
    duration   = get_audio_duration(audio_path)
    print(f"    → {duration:.1f}s audio")

    # 4. Background footage
    if mode == "spiritual":
        print("🎥   Downloading spiritual image montage assets (Pexels)...")
        image_paths = fetch_spiritual_background_images(scripted.get("search_keywords", []), job_dir)
        print(f"    → Downloaded {len(image_paths)} images")
        bg_path = build_image_montage(image_paths, duration, job_dir)
        print("    → Built warm spiritual montage")
    else:
        print("🎥   Downloading background footage (Pexels)...")
        bg_path = fetch_background_video(scripted.get("search_keywords", ["nature"]), job_dir)
        print(f"    → Downloaded")

    # 5. Compose
    print("🎞️   Composing video (FFmpeg)...")
    video_path = compose_video(bg_path, audio_path, scripted["script"], scripted["video_title"], job_dir)

    size_mb = video_path.stat().st_size / 1_000_000
    upload_meta = build_upload_metadata(content, scripted, video_path, duration)
    upload_meta["visual_style"] = (
        "Warm color spiritual montage with ancient Indian temples, deity statues, "
        "palaces, and sacred architecture; no black-and-white treatment or heavy text boxes."
    )
    (job_dir / "upload_metadata.json").write_text(json.dumps(upload_meta, indent=2))
    print(f"\n✅  Done!")
    print(f"    📁  {video_path}")
    print(f"    📏  {size_mb:.1f} MB  |  ⏱️  {duration:.1f}s")
    print(f"    🏷️   {' '.join(scripted.get('hashtags', []))}\n")
    return video_path


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="AI short-form video pipeline.")
    parser.add_argument(
        "--mode", "-m", default=DEFAULT_MODE, choices=VALID_MODES,
        help=f"Content type: reddit | news | history | spiritual (default: {DEFAULT_MODE})"
    )
    parser.add_argument(
        "--topic", "-t", default=None,
        help=(
            "Optional topic focus.\n"
            "  reddit:   subreddit name (e.g. AITA)\n"
            "  news:     topic keyword (e.g. 'technology')\n"
            "  spiritual: Gita theme (e.g. 'karma', 'duty', 'fear')\n"
            "  history:  ignored (uses today's date automatically)"
        )
    )
    parser.add_argument(
        "--time-filter", default="week",
        choices=["day", "week", "month", "year", "all"],
        help="Reddit only: time filter for top posts (default: week)"
    )
    args = parser.parse_args()
    run_pipeline(mode=args.mode, topic=args.topic, time_filter=args.time_filter)
