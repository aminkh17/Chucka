#!/usr/bin/env python3
"""Generate the podcast voice note with the local VoiceStudio API (OmniVoice engine).

VoiceStudio must be running: its OpenAI-compatible speech endpoint lives on
http://127.0.0.1:3900/v1/audio/speech while the app is open. The engine
understands inline non-verbal tags such as [laughter] and [sigh] in the text.

The voice is given by profile name ("Amin1", "Farah", ...) or profile id.
Energy knobs:
  PODCAST_VS_SPEED     speaking rate, default 1.08 — Farah's picked morning pace
  PODCAST_VS_INSTRUCT  voice-design style, e.g. "young adult, high pitch"
                       (only sent when set; combine with a clone at your own ear)
"""
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("VOICESTUDIO_URL", "http://127.0.0.1:3900")
VOICE = os.environ.get("PODCAST_VS_VOICE", "Farah")
SPEED = float(os.environ.get("PODCAST_VS_SPEED", "1.08"))
INSTRUCT = os.environ.get("PODCAST_VS_INSTRUCT", "").strip()
ENGINE = os.environ.get("PODCAST_VS_ENGINE", "omnivoice")
NUM_STEP = int(os.environ.get("PODCAST_VS_NUM_STEP", "32"))  # 32 = model's quality preset
FFMPEG = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"


def resolve_voice(name_or_id):
    """Accept a profile name ("Farah") or a raw id; return the profile id."""
    try:
        with urllib.request.urlopen(BASE + "/v1/audio/voices", timeout=10) as r:
            voices = json.load(r).get("voices", [])
    except Exception:
        return name_or_id  # let the speech endpoint decide (or fail with its own error)
    key = name_or_id.strip().lower()
    for v in voices:
        if key in (str(v.get("voice_id", "")).lower(), str(v.get("name", "")).lower()):
            return v["voice_id"]
    profiles = ", ".join(sorted(v["name"] for v in voices if v.get("type") == "profile"))
    sys.exit(f"no VoiceStudio voice matches {name_or_id!r} — available: {profiles}")


def main(text_file, out_file):
    with open(text_file, encoding="utf-8") as f:
        text = f.read().strip()
    if not text:
        sys.exit(f"script is empty: {text_file}")

    body = {
        "input": text,
        "voice": resolve_voice(VOICE),
        "model": ENGINE,
        "response_format": "mp3",
        "num_step": NUM_STEP,
        "language": "en",
        "denoise": True,
        "speed": SPEED,
    }
    if INSTRUCT:
        body["instruct"] = INSTRUCT
    req = urllib.request.Request(
        BASE + "/v1/audio/speech",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=420) as r:
            mp3 = r.read()
    except urllib.error.HTTPError as e:
        sys.exit(f"VoiceStudio HTTP {e.code}: {e.read()[:300]}")
    except Exception as e:
        sys.exit(f"VoiceStudio unreachable: {e}")

    tmp = out_file + ".mp3"
    with open(tmp, "wb") as f:
        f.write(mp3)
    try:
        # WhatsApp voice notes must be Ogg/Opus, mono; loudness-normalised so playback is even.
        subprocess.run(
            [FFMPEG, "-y", "-loglevel", "error", "-i", tmp, "-ac", "1", "-ar", "48000",
             "-c:a", "libopus", "-b:a", "32k", "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", out_file],
            check=True,
        )
    finally:
        os.remove(tmp)
    print(out_file)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
