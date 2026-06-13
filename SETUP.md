# Setup

See [README.md](README.md) for the current spiritual-first setup and run commands.

Quick start:

```bash
cp .env.example .env
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python pipeline.py --mode spiritual
```

The default content lane is Bhagavad Gita / spiritual wisdom. Generated videos and upload metadata are written under `output/<timestamp>/`.

Anthropic is optional for the default spiritual lane. Keep `SCRIPT_ENGINE=template` to run without it.
ElevenLabs is optional for local testing. Keep `TTS_ENGINE=local` to use macOS narration.
