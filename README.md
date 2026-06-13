# AI Content Pipeline

Spiritual-first short-form video generator for TikTok, Instagram Reels, and YouTube Shorts.

The current default lane is Bhagavad Gita / spiritual wisdom. A daily run finds a Gita teaching with Tavily, writes an original short narration with the local template writer, generates voiceover with local macOS TTS for testing, pulls a sequence of relevant Pexels images, and composes a warm 9:16 MP4 with FFmpeg.

## What It Produces

Each run creates a timestamped folder in `output/`:

```text
output/<timestamp>/
  final_video.mp4
  narration.mp3
  background.mp4
  captions.srt
  script.txt
  metadata.json
  upload_metadata.json
```

`upload_metadata.json` is the handoff file for publishing. It includes:

- a ready-to-upload title, caption, description, hashtags, and alt text
- TikTok caption payload
- Instagram Reels caption payload
- YouTube Shorts title, description, tags, category, and made-for-kids flag

## Visual Direction

Spiritual videos use a warm, full-color image montage. The search direction favors:

- ancient Indian temples and sacred architecture
- Hindu deity statues and devotional objects
- Indian palaces, maharaja/royal architecture, and temple sculpture
- saturated color grading; grayscale-looking assets are filtered out

Text is intentionally light: no full-screen black overlay, no heavy black title box, and short caption phrases so the background imagery remains visible.

## Requirements

- Python 3.10+
- FFmpeg, or the `imageio-ffmpeg` Python package from `requirements.txt`
- API keys for Tavily and Pexels
- Optional: ElevenLabs, only if you set `TTS_ENGINE=elevenlabs`
- Optional: Anthropic, only if you set `SCRIPT_ENGINE=anthropic`

Install FFmpeg on macOS if you have Homebrew:

```bash
brew install ffmpeg
```

If you do not have Homebrew, `imageio-ffmpeg` from `requirements.txt` supplies a local FFmpeg binary for the pipeline.

Install Python dependencies:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

## Configure

Create a local `.env` file:

```bash
cp .env.example .env
```

Fill in:

```text
TAVILY_API_KEY=...
PEXELS_API_KEY=...
```

Optional:

```text
ANTHROPIC_MODEL=claude-opus-4-8
ANTHROPIC_API_KEY=...
SCRIPT_ENGINE=template
TTS_ENGINE=local
LOCAL_TTS_VOICE=Samantha
ELEVENLABS_API_KEY=...
ELEVENLABS_VOICE_ID=21m00Tcm4TlvDq8ikWAM
SPIRITUAL_TOPIC=karma
```

Use `SCRIPT_ENGINE=template` to run without Anthropic. Use `SCRIPT_ENGINE=anthropic` if you want Claude to write richer scripts.
Use `TTS_ENGINE=local` for immediate test videos on macOS. Use `TTS_ENGINE=elevenlabs` when you want production-quality narration.

Leave `SPIRITUAL_TOPIC` blank for the automated daily rotation.

## Run Spiritual/Gita Mode

Default daily spiritual run:

```bash
.venv/bin/python pipeline.py
```

Specific spiritual topic:

```bash
.venv/bin/python pipeline.py --topic karma
.venv/bin/python pipeline.py --topic "inner peace"
.venv/bin/python pipeline.py --topic dharma
```

Explicit mode:

```bash
.venv/bin/python pipeline.py --mode spiritual --topic devotion
```

## Other Modes

The script still supports older content lanes:

```bash
.venv/bin/python pipeline.py --mode reddit --topic AITA --time-filter week
.venv/bin/python pipeline.py --mode news --topic technology
.venv/bin/python pipeline.py --mode history
```

Reddit mode additionally requires `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, and `REDDIT_USER_AGENT`.

## Daily Automation

The intended daily command is:

```bash
.venv/bin/python pipeline.py --mode spiritual
```

For unattended runs, keep `.env` on the machine that runs the schedule and make sure FFmpeg and Python dependencies are installed there. The pipeline chooses a rotating Gita topic each day when `SPIRITUAL_TOPIC` is blank.

## Safety Notes

- Do not commit `.env`.
- Rotate any API key that has been pasted into chat, email, docs, or source control.
- `output/` is ignored by git because generated videos can be large.
- Review generated spiritual scripts before publishing if you need scriptural precision or brand-specific voice.
