#!/usr/bin/env python3
"""Fallback voice note via Google Gemini TTS — used when VoiceStudio is unavailable.

Reads GEMINI_API_KEY from the environment or the project .env, sends the script
text to the Gemini TTS API and writes the same output contract as the other
tiers (Ogg/Opus mono, loudness-normalised). Inline [tags] are VoiceStudio-only,
so they are stripped before speaking. Note: natural-language style instructions
in the text are read aloud by this model, so the script is sent plain.
"""
import base64
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
import wave

ROOT = os.path.dirname(os.path.abspath(__file__))
MODEL = os.environ.get("PODCAST_GEMINI_MODEL", "gemini-3.8-flash-tts")
VOICE = os.environ.get("PODCAST_GEMINI_VOICE", "Kore")
FFMPEG = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def load_key():
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if key:
        return key
    try:
        with open(os.path.join(ROOT, ".env"), encoding="utf-8") as f:
            for line in f:
                if line.strip().startswith("GEMINI_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    sys.exit("no GEMINI_API_KEY in environment or .env")


def ssl_ctx():
    ctx = ssl.create_default_context()
    if not ctx.cert_store_stats()["x509_ca"]:
        ctx = ssl.create_default_context(cafile="/etc/ssl/cert.pem")
    return ctx


def main(text_file, out_file):
    with open(text_file, encoding="utf-8") as f:
        text = f.read().strip()
    # [laughter]/[sigh]/[pause ...] are VoiceStudio tags — Gemini would read them aloud.
    text = re.sub(r"\[[^\]]*\]", "", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    if not text:
        sys.exit(f"script is empty: {text_file}")

    body = {
        "contents": [{"parts": [{"text": text}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {
                "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": VOICE}}
            },
        },
    }
    req = urllib.request.Request(
        URL.format(model=MODEL),
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "x-goog-api-key": load_key()},
    )
    try:
        with urllib.request.urlopen(req, timeout=180, context=ssl_ctx()) as r:
            resp = json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"Gemini TTS HTTP {e.code}: {e.read()[:300]}")
    except Exception as e:
        sys.exit(f"Gemini TTS unreachable: {e}")

    try:
        part = next(p for p in resp["candidates"][0]["content"]["parts"]
                    if "inlineData" in p)
        mime = part["inlineData"]["mimeType"]
        data = base64.b64decode(part["inlineData"]["data"])
    except (KeyError, IndexError, StopIteration):
        sys.exit(f"Gemini TTS returned no audio: {json.dumps(resp)[:400]}")

    if "L16" in mime:
        # Raw 16-bit PCM — wrap it in a WAV container for ffmpeg.
        rate = int(re.search(r"rate=(\d+)", mime).group(1)) if "rate=" in mime else 24000
        tmp = out_file + ".pcm.wav"
        with wave.open(tmp, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(data)
    else:
        ext = ".mp3" if "mpeg" in mime or "mp3" in mime else ".wav" if "wav" in mime else ".bin"
        tmp = out_file + ext
        with open(tmp, "wb") as f:
            f.write(data)
    try:
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
