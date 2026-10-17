#!/usr/bin/env python3
"""Turn the podcast script text into a WhatsApp-ready voice note using macOS say."""
import os
import re
import shutil
import subprocess
import sys

VOICE = os.environ.get("PODCAST_VOICE", "Samantha")
RATE = os.environ.get("PODCAST_RATE", "175")
# launchd runs this job with a minimal PATH, so resolve tools explicitly.
SAY = shutil.which("say") or "/usr/bin/say"
FFMPEG = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"


def main(text_file, out_file):
    if not os.path.isfile(text_file):
        sys.exit(f"no script at {text_file}")
    with open(text_file, encoding="utf-8") as f:
        text = f.read().strip()
    # Inline TTS tags ([laughter], [sigh], [pause 300ms]) are for the VoiceStudio engine —
    # this fallback must never read them out loud.
    text = re.sub(r"\[[^\]]*\]", "", text)
    text = re.sub(r"\s{2,}", " ", text).strip()
    if not text:
        sys.exit(f"script is empty: {text_file}")

    aiff = os.path.splitext(out_file)[0] + ".aiff"
    say_text = os.path.splitext(out_file)[0] + ".say.txt"
    with open(say_text, "w", encoding="utf-8") as f:
        f.write(text)
    try:
        subprocess.run([SAY, "-v", VOICE, "-r", RATE, "-o", aiff, "-f", say_text], check=True)
    finally:
        os.remove(say_text)
    # WhatsApp voice notes must be Ogg/Opus, mono; loudness-normalised so phone playback is even.
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-i", aiff,
                    "-ac", "1", "-ar", "48000", "-c:a", "libopus", "-b:a", "32k",
                    "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", out_file], check=True)
    os.remove(aiff)
    print(out_file)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
