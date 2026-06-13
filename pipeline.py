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
  - Anthropic Claude      → scriptwriting + copyright-safe rewriting
  - ElevenLabs            → text-to-speech narration
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
from datetime import datetime
from pathlib import Path

import requests
import praw
from anthropic import Anthropic
from tavily import TavilyClient
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
REDDIT_CLIENT_ID     = os.getenv("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET = os.getenv("REDDIT_CLIENT_SECRET", "")
REDDIT_USER_AGENT    = os.getenv("REDDIT_USER_AGENT", "ContentBot/1.0")

ELEVENLABS_API_KEY  = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")  # Rachel

PEXELS_API_KEY    = os.getenv("PEXELS_API_KEY", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
TAVILY_API_KEY    = os.getenv("TAVILY_API_KEY", "")

OUTPUT_DIR = Path("output")
TEMP_DIR   = Path("temp")

DEFAULT_SUBREDDITS = ["AITA", "tifu", "confessions", "TrueOffMyChest"]

VIDEO_W, VIDEO_H, VIDEO_FPS = 1080, 1920, 30
WPS = 2.8   # words per second (ElevenLabs pacing)

VALID_MODES = ["reddit", "news", "history", "spiritual"]


# ─────────────────────────────────────────────
# UTILITIES
# ─────────────────────────────────────────────

def check_deps(mode: str):
    # FFmpeg
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        print("❌  FFmpeg not found. Install with:  brew install ffmpeg")
        sys.exit(1)

    missing = []
    if not ELEVENLABS_API_KEY: missing.append("ELEVENLABS_API_KEY")
    if not PEXELS_API_KEY:     missing.append("PEXELS_API_KEY")
    if not ANTHROPIC_API_KEY:  missing.append("ANTHROPIC_API_KEY")
    if mode == "reddit" and (not REDDIT_CLIENT_ID or not REDDIT_CLIENT_SECRET):
        missing.append("REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET")
    if mode in ("news", "history", "spiritual") and not TAVILY_API_KEY:
        missing.append("TAVILY_API_KEY")
    if missing:
        print("❌  Missing environment variables in .env:")
        for m in missing:
            print(f"    • {m}")
        print("\n   Copy .env.example → .env and fill in the values.")
        sys.exit(1)


def get_audio_duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True
    )
    return float(result.stdout.strip())


def seconds_to_srt_time(s: float) -> str:
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    sec = s % 60
    return f"{h:02d}:{m:02d}:{sec:06.3f}".replace(".", ",")


def build_srt(script: str, wps: float = WPS) -> str:
    sentences = re.split(r'(?<=[.!?])\s+', script.strip())
    lines = []
    t = 0.0
    for i, sentence in enumerate(sentences, 1):
        words = len(sentence.split())
        dur   = max(1.5, words / wps)
        start = seconds_to_srt_time(t)
        end   = seconds_to_srt_time(t + dur)
        wrapped = "\n".join(textwrap.wrap(sentence, width=36))
        lines.append(f"{i}\n{start} --> {end}\n{wrapped}\n")
        t += dur + 0.1
    return "\n".join(lines)


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
    client = TavilyClient(api_key=TAVILY_API_KEY)
    query = (
        f"Bhagavad Gita verse about {topic} full translation meaning explanation"
        if topic else
        "most powerful Bhagavad Gita verse full Sanskrit translation meaning life lesson"
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


def write_script(content: dict) -> dict:
    """Use Claude to write the final video script from raw source content."""
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
        model="claude-opus-4-8",
        max_tokens=1024,
        system=system,
        messages=[{"role": "user", "content": user_msg}]
    )

    raw = resp.content[0].text.strip()
    raw = re.sub(r"^```[a-z]*\n?", "", raw)
    raw = re.sub(r"\n?```$", "", raw)
    return json.loads(raw)


# ─────────────────────────────────────────────
# NARRATION (ElevenLabs)
# ─────────────────────────────────────────────

def generate_narration(script: str, out_dir: Path) -> Path:
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


# ─────────────────────────────────────────────
# BACKGROUND FOOTAGE (Pexels)
# ─────────────────────────────────────────────

def fetch_background_video(keywords: list, out_dir: Path) -> Path:
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


# ─────────────────────────────────────────────
# VIDEO COMPOSITION (FFmpeg)
# ─────────────────────────────────────────────

def compose_video(bg_path, audio_path, script, title, out_dir) -> Path:
    duration = get_audio_duration(audio_path)
    font     = system_font()

    srt_path = out_dir / "captions.srt"
    srt_path.write_text(build_srt(script), encoding="utf-8")

    safe_title = title.replace("'", "\\'").replace(":", "\\:").replace("\\", "\\\\")[:55]
    font_arg   = f":fontfile='{font}'" if font else ""

    sub_style = (
        "Fontsize=22,Bold=1,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
        "Outline=2,Shadow=1,Alignment=2,MarginV=80"
    )

    filter_complex = (
        f"[0:v]"
        f"scale={VIDEO_W}:{VIDEO_H}:force_original_aspect_ratio=increase,"
        f"crop={VIDEO_W}:{VIDEO_H},setsar=1,setpts=PTS-STARTPTS[bg];"
        f"[bg]drawbox=x=0:y=0:w={VIDEO_W}:h={VIDEO_H}:color=black@0.45:t=fill[dark];"
        f"[dark]drawtext=text='{safe_title}'{font_arg}:fontsize=46:fontcolor=white:"
        f"x=(w-text_w)/2:y=80:box=1:boxcolor=black@0.55:boxborderw=18:line_spacing=6[titled];"
        f"[titled]subtitles='{srt_path}':force_style='{sub_style}'[out]"
    )

    out_path = out_dir / "final_video.mp4"
    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "-1",
        "-i", str(bg_path),
        "-i", str(audio_path),
        "-t", str(math.ceil(duration) + 1),
        "-filter_complex", filter_complex,
        "-map", "[out]", "-map", "1:a",
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        str(out_path)
    ]

    print("   Running FFmpeg (~30 seconds)...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print("FFmpeg error:\n", result.stderr[-2000:])
        raise RuntimeError("FFmpeg composition failed.")
    return out_path


# ─────────────────────────────────────────────
# MAIN PIPELINE
# ─────────────────────────────────────────────

def run_pipeline(mode: str = "reddit", topic: str = None, time_filter: str = "week") -> Path:
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

    # 2. Write script with Claude
    print("✍️   Writing script with Claude...")
    scripted   = write_script(content)
    word_count = len(scripted["script"].split())
    print(f"    → Title:  {scripted['video_title']}")
    print(f"    → Script: {word_count} words (~{round(word_count/WPS)}s narration)")

    # Save metadata
    meta = {**content, **scripted, "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ")}
    (job_dir / "metadata.json").write_text(json.dumps(meta, indent=2))
    (job_dir / "script.txt").write_text(scripted["script"])

    # 3. ElevenLabs narration
    print("🎙️   Generating narration (ElevenLabs)...")
    audio_path = generate_narration(scripted["script"], job_dir)
    duration   = get_audio_duration(audio_path)
    print(f"    → {duration:.1f}s audio")

    # 4. Background footage
    print("🎥   Downloading background footage (Pexels)...")
    bg_path = fetch_background_video(scripted.get("search_keywords", ["nature"]), job_dir)
    print(f"    → Downloaded")

    # 5. Compose
    print("🎞️   Composing video (FFmpeg)...")
    video_path = compose_video(bg_path, audio_path, scripted["script"], scripted["video_title"], job_dir)

    size_mb = video_path.stat().st_size / 1_000_000
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
        "--mode", "-m", default="reddit", choices=VALID_MODES,
        help="Content type: reddit | news | history | spiritual (default: reddit)"
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
