# Social Media Content Pipeline — Setup Guide

Generates a ready-to-post TikTok / Instagram Reels / YouTube Shorts video from a Reddit story in ~2 minutes.

---

## Prerequisites

### 1. Python 3.10+
```bash
python3 --version   # should print 3.10 or higher
```

### 2. FFmpeg (video compositor)
```bash
brew install ffmpeg          # macOS (Homebrew)
# or: sudo apt install ffmpeg  # Ubuntu/Debian
```

---

## Install Python dependencies

```bash
cd /path/to/this/folder
pip install -r requirements.txt
```

---

## Get your API keys (all free to start)

### Reddit API — free
1. Go to https://www.reddit.com/prefs/apps
2. Scroll down → click **"create another app..."**
3. Select **"script"**
4. Name: `ContentBot`, redirect URI: `http://localhost`
5. Click **"create app"**
6. Copy the **client ID** (short string under "personal use script") and **client secret**

### Pexels API — completely free, no credit card
1. Go to https://www.pexels.com/api/
2. Sign up for a free account
3. Click **"Your API Key"** — it's instant
4. 200 requests/hour, 20,000/month — plenty for daily posting

### ElevenLabs — you already have tokens
1. Go to https://elevenlabs.io → Profile icon → **API Key**
2. Copy your key
3. To pick a voice: https://elevenlabs.io/voice-library → find one you like → copy its Voice ID
   - Popular choices: Rachel (21m00Tcm4TlvDq8ikWAM), Adam (pNInz6obpgDQGcFmaJgB)

### Anthropic API — for story rewriting
1. Go to https://console.anthropic.com → API Keys → **Create Key**
2. Cost per video: ~$0.01–0.02 (very cheap — claude-opus-4-8 is only called once per video)

---

## Configure

Copy `.env.example` to `.env` and fill in your keys:

```bash
cp .env.example .env
# then open .env and add your keys
```

---

## Run

```bash
# Random subreddit, top posts from this week
python3 pipeline.py

# Specific subreddit
python3 pipeline.py --subreddit AITA

# Top posts from today (more timely content)
python3 pipeline.py --subreddit tifu --time day
```

Output is saved to `output/<timestamp>/final_video.mp4`
The folder also contains `metadata.json` with the title, hashtags, and script.

---

## Cost breakdown (daily posting = 30 videos/month)

| Service       | Plan          | Cost/month  | Notes                                  |
|---------------|---------------|-------------|----------------------------------------|
| ElevenLabs    | Starter       | $5          | 30,000 chars/mo ≈ 60 videos            |
| ElevenLabs    | Creator       | $22         | 100,000 chars/mo ≈ 200 videos          |
| Anthropic     | Pay-as-you-go | ~$0.50      | ~$0.015 per video for Claude rewriting |
| Pexels        | Free          | $0          | No limits for this use case            |
| Reddit API    | Free          | $0          | Unlimited reads                        |
| **Total**     |               | **~$5–22**  | Depending on ElevenLabs tier           |

**ElevenLabs tip:** Each video uses ~175 words ≈ ~900 characters. The $5 Starter plan (30,000 chars) covers ~33 videos — just enough for daily posting. Upgrade to Creator ($22) for comfortable headroom.

**Alternative TTS (free):** If you want to reduce costs, the pipeline can be adapted to use `gTTS` (Google Text-to-Speech, free) or `pyttsx3` (offline). Quality is lower but zero cost.

---

## Automate with a daily schedule

Once the pipeline runs correctly, you can schedule it with Cowork's scheduling feature to run automatically every day and generate a fresh video.

---

## Copyright approach

This pipeline is designed to be **copyright-safe** by default:
- Claude **completely rewrites** every story — no sentences are copied verbatim
- All names, locations, and identifying details are replaced with generic/fictional ones
- Background footage from Pexels is royalty-free (Pexels License — free for commercial use)
- The output is **original content inspired by** Reddit, not a reproduction of it

This transformative approach is standard practice among successful Reddit story channels.

---

## Output folder structure

```
output/
└── 1718300000/
    ├── final_video.mp4    ← upload this
    ├── narration.mp3      ← audio only
    ├── background.mp4     ← raw background footage
    ├── captions.srt       ← subtitle file
    ├── script.txt         ← narration text
    └── metadata.json      ← title, hashtags, source info
```
