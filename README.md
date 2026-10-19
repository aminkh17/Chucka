# Chucka (aka MorningDashboard)

A personal morning briefing that turns an [Obsidian](https://obsidian.md) vault into two things, delivered to WhatsApp every day at 07:00:

1. **a dashboard PNG** (1080×1920, phone-friendly) — top must-dos, job pipeline, project status, study/write queues
2. **a ~60-second voice note** — a spoken version of the same board, written each morning by an LLM and spoken by a local voice-cloning engine

Built for macOS. Opinionated, single-user, no server.

## How it works

```
Obsidian vault ──┬─> generate_dashboard.py ──────────────> dashboard PNG ─┐
                 │                                                        │
                 └─> generate_podcast_script.py ──> script text           │
                          (vault + weather + opencode CLI)                │
                               │                                         ▼
                               └─> tts_voicestudio.py   (local VoiceStudio / OmniVoice, cloned voice)
                                   tts_gemini.py        (Google Gemini TTS fallback)
                                   text_to_voice.py     (macOS `say`, last resort)
                                        │
                                        └─> voice note (.ogg / Opus) ────┐
                                                                         ▼
run-morning.sh  ──────────────────────────────────────>  send_whatsapp.py / send_voice.py
                                                          (OpenWA gateway → WhatsApp, waits for delivery)
```

- **Dashboard** — reads the vault live and renders with Pillow: jobs from the `Job Hunting/*.md` table, projects from `Projects/`, tasks picked up by `#tag`s.
- **Podcast script** — feeds the same data plus Melbourne weather (wttr.in) to the [opencode](https://opencode.ai) CLI (model configurable), which writes a ~170-word spoken summary with a fresh greeting every day. The last three openings are fed back so it never repeats one.
- **Voice** — three tiers, all producing the same output (Ogg/Opus mono, loudness-normalised):
  1. `tts_voicestudio.py` — local [VoiceStudio](https://github.com/debpalash/VoiceStudio) app (OmniVoice engine, `k2-fsa/OmniVoice`): your own cloned voice, inline emotion tags like `[laughter]` / `[sigh]` supported
  2. `tts_gemini.py` — Google Gemini TTS (`gemini-3.8-flash-tts`): cloud fallback when VoiceStudio is unavailable
  3. `text_to_voice.py` — macOS `say`: always works, no dependencies
- **Delivery** — [OpenWA](https://open-wa.org) (unofficial WhatsApp Web gateway) sends the image, then the voice note as a real PTT bubble. Both wait for a `delivered`/`read` confirmation before the job finishes. The runner starts the gateway only when needed and stops what it started.
- **Schedule** — a launchd agent runs `run-morning.sh` daily at 07:00. A single day's failure (Mac asleep, vault unreadable, script generation down) degrades gracefully: the image still goes out even if the voice can't be made.

## Priority model

Every job, project and task is scored from signals already in your vault — job stage and
temperature, follow-up staleness, project next-actions and open tasks, task type and urgency
words, plus priority inheritance from the task's project — then banded within its lane:

- **P1** — do first (one per lane)
- **P2** — next up
- **P3** — later

The three P1s — best job, best project, best task — are the day's **Top 3**, matching the
morning rule (1 submit • 1 code • 1 study). The PNG writes `out/priorities-<date>.json` and
the podcast generator reads it, so the image and the voice note always agree.

Override with `#p1` / `#p2` / `#p3` on any task line, or `priority:: 1|2|3` anywhere in a
project note. Explicit tags beat the computed score, in ordering and in banding.

## Requirements

| Thing | Why | Notes |
|---|---|---|
| macOS | launchd, `say`, `/usr/bin/open` | tested on Apple Silicon |
| Python 3.9+ | all scripts | `pip install pillow` |
| ffmpeg | voice encoding | `brew install ffmpeg` |
| [opencode CLI](https://opencode.ai) | writes the podcast script | any reachable model works |
| [OpenWA](https://open-wa.org) | WhatsApp gateway | separate project; link your session once by scanning a QR code |
| VoiceStudio *(optional)* | the good voice | profiles are made in its UI; it exposes a local API on port 3900 |
| Gemini API key *(optional)* | voice fallback | [aistudio.google.com](https://aistudio.google.com), free tier |

## Setup

1. **Clone** this repo and OpenWA next to it:

   ```sh
   git clone <this-repo> ~/Chucka && cd ~/Chucka
   git clone https://github.com/<openwa-repo> OpenWA     # your OpenWA checkout
   ```

2. **Configure**: `cp .env.example .env` and fill in your vault path, phone number, and OpenWA session name. Absolute binaries (`PYTHON_BIN`, `OPENWA_NODE`) are required because launchd runs with a minimal PATH.

3. **Link WhatsApp** once: start OpenWA, open its dashboard, scan the QR code, note the session name — that's `OPENWA_SESSION` in `.env`.

4. **Make sure the API key file exists** at `OpenWA/data/.api-key` (OpenWA creates it on first run).

5. **Test the pieces**, then the whole run:

   ```sh
   python3 generate_dashboard.py        # renders out/morning-dashboard-YYYY-MM-DD.png
   ./run-morning.sh                     # the full end-to-end (sends real messages!)
   ```

6. **Install the daily 07:00 job** (see the header of `com.morningdashboard.plist.example` for the exact commands):

   ```sh
   sed "s|/PATH/TO/Chucka|$PWD|g; s|com.morningdashboard|com.$(whoami).morningdashboard|g" \
     com.morningdashboard.plist.example > ~/Library/LaunchAgents/com.$(whoami).morningdashboard.plist
   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.$(whoami).morningdashboard.plist
   launchctl kickstart gui/$(id -u)/com.$(whoami).morningdashboard   # run it right now
   ```

## Configuration

Everything lives in `.env` (see `.env.example` for the full list with comments):

| Variable | Default | Purpose |
|---|---|---|
| `VAULT` | — | Obsidian vault path (required) |
| `WA_TO` | — | destination number, international format (required) |
| `OPENWA_SESSION` | — | OpenWA session name (required) |
| `PYTHON_BIN`, `OPENWA_NODE` | `python3`, `node` | absolute binary paths for launchd |
| `OPENCODE_BIN`, `PODCAST_MODEL` | `/opt/homebrew/bin/opencode`, `opencode/deepseek-v4.1-flash-free` | script generation |
| `PODCAST_VS_VOICE`, `PODCAST_VS_SPEED` | `Farah`, `1.08` | VoiceStudio profile (name or id) and pace |
| `PODCAST_VS_INSTRUCT` | *(empty)* | optional voice-design style for VoiceStudio |
| `PODCAST_GEMINI_VOICE`, `GEMINI_API_KEY` | `Kore`, *(empty)* | Gemini fallback |
| `PODCAST_VOICE`, `PODCAST_RATE` | `Samantha`, `175` | macOS `say` fallback |

## Privacy

- Your vault never leaves the machine — only the **script text** goes to the LLM via opencode (and to Gemini **only** if the Gemini voice fallback runs).
- Weather comes from wttr.in. Messages go through *your own* OpenWA gateway — no third-party push service.
- `.env`, `out/`, `podcast/`, `logs/` and `OpenWA/` are gitignored; the repo contains no personal data.

## Troubleshooting

- **Nothing arrived** — check `logs/morning.log`; message sends must *not* stop the gateway until a `delivered`/`read` confirmation (the runner handles this — keep it).
- **"Session needs re-linking"** — WhatsApp unlinked the session; scan the QR code again in the OpenWA dashboard.
- **Wrong/robotic voice** — VoiceStudio wasn't reachable: the log line says which tier was used (`VoiceStudio` / `Gemini fallback` / `say fallback`). VoiceStudio's model cold-loads after ~15 min idle (~10–20 s).
- **`ffmpeg not found` under launchd** — set absolute paths in `.env`; launchd's PATH is minimal.
- **Mac asleep at 07:00** — the job runs on wake; `sudo pmset repeat wakeorpoweron MTWRFSU 06:58:00` fixes the timing.

## Repo layout

```
priority.py                 scoring + Top 3, shared by the PNG and the voice
generate_dashboard.py       vault → PNG (+ out/priorities-<date>.json)
generate_podcast_script.py  vault + weather → script via opencode CLI (same ranking)
tts_voicestudio.py          script → voice (VoiceStudio)
tts_gemini.py               script → voice (Gemini)
text_to_voice.py            script → voice (macOS say)
send_whatsapp.py            PNG → WhatsApp (OpenWA)
send_voice.py               voice note → WhatsApp (OpenWA)
envload.py                  loads .env into the environment
run-morning.sh              the daily job (render → voice → send)
com.morningdashboard.plist.example  launchd agent, 07:00 daily
```

## License

[MIT](LICENSE)
