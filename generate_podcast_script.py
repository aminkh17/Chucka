#!/usr/bin/env python3
"""Generate the spoken podcast script for the morning dashboard via the opencode CLI.

Two passes: (1) the plain brief, (2) a performance pass that adds only the non-verbal tags
OmniVoice actually understands — never emotion labels, which the engine would speak aloud.
The untagged script feeds the fallback TTS tiers; the tagged one feeds VoiceStudio.
"""
import datetime as dt
import difflib
import glob
import json
import os
import re
import ssl
import subprocess
import sys
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from generate_dashboard import load_jobs, load_projects, load_tasks, load_completed_tasks, clean  # noqa: E402
from priority import build_payload  # noqa: E402

import envload; envload.load_env()  # noqa: E402

VAULT = os.environ.get("VAULT", "")
# Leave model selection to OpenCode's configured default unless explicitly overridden.
MODEL = os.environ.get("PODCAST_MODEL", "").strip()
OPENCODE = os.environ.get("OPENCODE_BIN", "/opt/homebrew/bin/opencode")
WEATHER_URL = "https://wttr.in/Melbourne?format=j1"
TODAY = dt.date.today()

# OmniVoice's complete non-verbal token set (from _NONVERBAL_PATTERN in the engine).
# These are sounds, not emotion labels: [excited], [happy], [short pause] etc. are NOT
# supported and would be spoken aloud literally.
TAG_GROUPS = {
    "English-friendly": ["laughter", "sigh", "confirmation-en", "question-en",
                         "surprise-ah", "surprise-oh", "dissatisfaction-hnn"],
    "Other-language interjections (avoid in English)": ["question-ah", "question-oh",
                                                        "question-ei", "question-yi",
                                                        "surprise-wa", "surprise-yo"],
}
ALLOWED_TAGS = {tag for tags in TAG_GROUPS.values() for tag in tags}
# Common spellings (including the variants shown in VoiceStudio's UI) → engine tokens.
TAG_ALIASES = {
    "laughs": "laughter", "laugh": "laughter", "giggles": "laughter",
    "giggle": "laughter", "chuckle": "laughter", "light chuckle": "laughter",
    "sighs": "sigh",
    "question-yil": "question-yi",
    "surprise-yol": "surprise-yo",
    "question-eil": "question-ei",
}
TAG_MENU = "\n".join(
    f"  {group}: " + ", ".join(f"[{tag}]" for tag in tags)
    for group, tags in TAG_GROUPS.items()
)
TAG_RE = re.compile(r"\[\s*([^\[\]]{1,40}?)\s*\]")


def weather():
    try:
        ctx = ssl.create_default_context()
        if not ctx.cert_store_stats()["x509_ca"]:
            ctx = ssl.create_default_context(cafile="/etc/ssl/cert.pem")
        with urllib.request.urlopen(WEATHER_URL, timeout=15, context=ctx) as r:
            d = json.load(r)
        cur, day = d["current_condition"][0], d["weather"][0]
        return {
            "temp_c": cur["temp_C"], "feels_c": cur["FeelsLikeC"],
            "desc": cur["weatherDesc"][0]["value"], "humidity": cur["humidity"],
            "min_c": day["mintempC"], "max_c": day["maxtempC"],
            "sunrise": day["astronomy"][0]["sunrise"], "sunset": day["astronomy"][0]["sunset"],
        }
    except Exception as e:  # weather is optional context
        print(f"weather unavailable: {e}", file=sys.stderr)
        return {"error": str(e)}


def recent_greetings(limit=3):
    """First lines of the last few scripts, so the model can avoid repeating itself."""
    out = []
    pattern = os.path.join(ROOT, "podcast", "script-[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9].txt")
    for p in sorted(glob.glob(pattern), reverse=True):
        if os.path.basename(p) == f"script-{TODAY:%Y-%m-%d}.txt":
            continue
        try:
            with open(p, encoding="utf-8") as f:
                first = f.readline().strip()
            if first:
                out.append(first)
        except OSError:
            pass
        if len(out) >= limit:
            break
    return out


def dashboard_summary():
    jobs, closed, updated = load_jobs()
    projects = load_projects()
    tasks, total = load_tasks()

    # Prefer the ranking the PNG just rendered, so both always agree.
    prio_path = os.path.join(ROOT, "out", f"priorities-{TODAY:%Y-%m-%d}.json")
    try:
        with open(prio_path, encoding="utf-8") as f:
            ranked = json.load(f)
    except OSError:
        ranked = build_payload(jobs, projects, tasks, TODAY)

    def iso(value):
        return value if isinstance(value, str) or value is None else value.isoformat()

    def task_rows(items, limit=6):
        return [{"task": t["text"], "priority": t["priority"], "due": iso(t.get("due")),
                 "project": t.get("project")} for t in items[:limit]]

    return {
        "jobs_updated": updated.isoformat() if updated else None,
        "top3": ranked["top3"],
        "active_roles": [
            {"company": j["company"], "role": j["role"], "stage": j["stage"],
             "last_activity": iso(j["last"]),
             "temperature": j["temp"], "next_move": j["next"],
             "priority": j["priority"], "priority_score": j["score"]}
            for j in ranked["jobs"]
        ],
        "closed": closed,
        "projects": [
            {"name": p["name"], "status": p["status"], "open_tasks": p["open"],
             "done_tasks": p["done"], "last_edited": iso(p["updated"]),
             "due": iso(p.get("due")), "priority": p["priority"],
             "priority_score": p["score"]}
            for p in ranked["projects"][:8]
        ],
        "open_tasks_total": total,
        "yesterday": {
            "date": (TODAY - dt.timedelta(days=1)).isoformat(),
            "completed_tasks": load_completed_tasks(TODAY - dt.timedelta(days=1)),
        },
        "study": task_rows(ranked["tasks"]["learn"]),
        "writing": task_rows(ranked["tasks"]["write"]),
        "reviews": task_rows(ranked["tasks"]["review"]),
        "focus": task_rows([t for t in ranked["tasks"].get("other", [])
                            if t.get("due") or t.get("explicit")]),
    }


PROMPT = f"""You write the spoken script for a short personal morning podcast.

The script is played right after the listener has received a PNG dashboard image in WhatsApp.
You are given the dashboard data below, which was already read from the Obsidian vault
({VAULT}). Use the obsidian MCP tools only if you need to confirm or
expand something important; the data below is authoritative and current.

Write the script so it is spoken out loud, not read:

1. Greeting: the opening must sound unmistakably Australian. Start with a recognisable Aussie
   greeting — "G'day", "G'day, Amin", "Morning, mate", "How ya going", "Righto" — woven into a
   creative, warm opening. Vary the choice of opener every day; never the same formula. Light
   slang only: one or two touches, never stacked, no caricatures. Keep the Aussie flavour in this
   greeting — the rest of the script stays plain, warm English. Play with the weekday, the date,
   the season, or the weather, and always include the weekday and the date. Do not reuse any of
   the openings listed in recent_greetings below.
2. One short sentence on the day and the Melbourne weather (use the weather data, name the
   temperature and describe the day briefly, mention if rain is likely). If the weather data
   contains an "error", skip the weather.
3. Yesterday's wins FIRST, before any overdue items or today's to-dos. Use
   dashboard.yesterday.completed_tasks: explicitly acknowledge what you accomplished yesterday,
   naming two or three concrete wins (or all if fewer), with project context when useful.
   Give this one or two warm, specific sentences, roughly 25 to 40 words when there are wins.
   These are dated completions, not things still to do. If the list is empty, briefly say
   "I don't have any recorded completions from yesterday" — never imply you did nothing.
   Do not infer yesterday's achievements from last_edited, total done_tasks, closed jobs,
   or a shrinking backlog; those do not establish when work was done.
4. Then explain today's priorities clearly, in this order:
   - "top3": the three must-dos for today — one job, one project, one task. They are
     already ranked: follow their exact order and explain why each one matters
    - briefly add job or project context only if it adds something beyond the Top 3; if one
     has a deadline, say whether it is overdue, due today, or how many days are left
    - mention a study, writing or focus task only if it is an important extra, not a backlog roll-call
5. Close with one motivating sentence. This closing line is required, always include it.

Rules:
- 45 to 70 seconds when spoken: roughly 120 to 180 words, no more.
- Plain spoken sentences. No markdown, no bullet points, no URLs, no emoji, no stage directions,
  and no bracketed tags of any kind — a second pass adds the engine's non-verbal tags afterwards.
- Rhythm comes from punctuation: short sentences, commas and dashes for pauses.
- Delivery energy: an informal, friendly breakfast-radio brief for a mate — bright, happy,
  energetic, short punchy sentences, upbeat verbs, the odd exclamation where it fits.
  Never flat or sleepy.
- Emotional shape: let the energy move with the content, in the writing itself. Greeting and
  close are the brightest — warm, upbeat, a little excited. The Top 3 is punchy and motivating.
  The weather is light and friendly. Job and project news is candid and wry, never gloomy — a
  stalled item gets a dry aside, not a dirge. Study and writing are brisk and practical. Use
  everyday interjections ("righto", "nice", "ah well", "here's the good bit") sparingly — a
  few at most, never a hype reel.
- Never read non-English names of companies letter by letter; say them naturally.
- Do not invent facts that are not in the data. If something is unknown, leave it out.
- Make room for yesterday's wins by shortening the backlog recap, never by dropping the wins.
  Do not repeat an item across sections or turn the whole briefing into an overdue list.
- Priority: today's ranked items carry a "priority" — P1 (do first), P2 (next), P3
  (later). The "top3" list is authoritative: never reorder it or promote something else.
- Address Amin directly as "you".
- Output only the script text.

DATA
----
"""


# Second opencode run. It receives the finished script and may only add non-verbal sounds.
PERFORMANCE_PROMPT = f"""You are the performance editor for a short personal morning podcast.

You receive the finished spoken script below. The voice engine is OmniVoice. It does NOT
understand emotion labels: [excited], [happy], [thoughtful], [whispers], [short pause] and
anything similar are not supported and would be spoken aloud or ignored. It understands only
these non-verbal tokens:

{TAG_MENU}

Your job: add a few of these sounds where a real person would naturally make them. The
emotional colour must come from the writing and punctuation, which are already informal,
friendly, happy, excited and energetic — these tags are occasional human noises, not a mood
track.

When to use what:
- [laughter] — something genuinely wry or funny. At most once.
- [sigh] — a stalled item, a long list, or relief. At most once.
- [surprise-ah] / [surprise-oh] — a real surprise, such as a deadline that is today.
- [dissatisfaction-hnn] — an overdue item or a wry complaint. At most once.
- [confirmation-en] — a confirming "mm-hm" after an affirmation.
- [question-en] — only after a genuine question, never as decoration.
- Prefer the English-friendly tokens above. Leave the other-language interjections alone in
  an English script.

Restraint:
- Aim for 1 or 2 sounds in the whole script; 0 is a perfectly good answer if nothing fits.
  Never more than 3.
- Do not tag every topic or section, and never stack two tags back to back.
- Put a tag where the sound happens, never inside a word, number or date.
- The greeting and close should stay the most energetic parts; don't smother them.

Hard rules:
- Do not change, add, remove, reorder or rewrite a single spoken word, name, number, date or
  fact. Keep the greeting, the weather, yesterday's wins, the Top 3 order and the closing line exactly as
  written. The only edits allowed are inserting tags and adjusting the spacing or punctuation
  immediately around them.
- Never invent a tag and never use any other bracketed text, markdown, emoji, headings,
  labels or notes. With the tags removed, the word count must still be 120 to 180 words.
- Output only the tagged script — the whole script, start to finish. Start immediately with
  the script's opening words: no preamble, no "here is", no commentary, no mention of tools,
  files, the repo or your process.
- If nothing genuinely fits, return the script unchanged.

SCRIPT
----
"""


def run_opencode(prompt, title, timeout=300):
    cmd = [OPENCODE, "run"]
    if MODEL:
        cmd += ["--model", MODEL]
    cmd += ["--auto", "--title", title, prompt]
    # cwd matters under launchd, which starts the job in "/": opencode picks up project context from it.
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=ROOT)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"opencode timed out after {timeout}s")
    if p.returncode != 0:
        raise RuntimeError(f"opencode failed ({p.returncode}): {p.stderr[-1500:]}")
    text = p.stdout.strip()
    text = re.sub(r"^```[a-z]*\n|\n```$", "", text).strip()
    if not text:
        raise RuntimeError("opencode returned no text")
    return text


def spoken_words(text):
    """Word count with the inline tags removed — tags are never spoken."""
    return len(TAG_RE.sub("", text).split())


def plain_text(text):
    """Lowercased text with tags removed and whitespace/punctuation normalised."""
    text = TAG_RE.sub("", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    return " ".join(text.lower().split())


def normalize_tag(raw):
    """Lowercase a tag and map known alternates to the engine's canonical spelling."""
    tag = re.sub(r"\s+", " ", raw.strip().lower())
    return TAG_ALIASES.get(tag, tag)


def sanitize_tags(text):
    """Keep only the tags the engine actually supports; drop anything invented."""
    def keep(match):
        tag = normalize_tag(match.group(1))
        return f"[{tag}]" if tag in ALLOWED_TAGS else ""

    text = TAG_RE.sub(keep, text)
    text = re.sub(r"(\[[a-z][a-z -]*\])(?:\s*\1)+", r"\1", text)             # no repeats
    text = re.sub(r"(\[[a-z][a-z -]*\])(?=[A-Za-z0-9'\"“])", r"\1 ", text)  # space after tag
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def starts_with_script(candidate, script):
    """True when the reply begins with the script, not a preamble."""
    return plain_text(candidate).startswith(plain_text(script)[:60])


def trim_preamble(tagged, script):
    """Drop leading lines the model added before the actual script."""
    if starts_with_script(tagged, script):
        return tagged
    lines = tagged.splitlines()
    for i in range(1, len(lines)):
        candidate = "\n".join(lines[i:]).strip()
        if starts_with_script(candidate, script):
            return candidate
    # Last resort for a same-line preamble: cut at the script's opening words.
    opening = " ".join(script.split()[:8])
    pos = tagged.find(opening)
    if pos > 0:
        return tagged[pos:].strip()
    return tagged


def text_similarity(a, b):
    """How closely the tagged text matches the original once tags and whitespace are gone."""
    return difflib.SequenceMatcher(None, plain_text(a), plain_text(b)).ratio()


def performance_pass(script):
    """Second opencode run: the same words, plus a few supported non-verbal sounds."""
    flag = os.environ.get("PODCAST_PERFORMANCE_TAGS",
                          os.environ.get("PODCAST_EMOTION_TAGS", "1"))
    if flag.strip().lower() in {"0", "false", "off", "no"}:
        print("performance pass disabled (PODCAST_PERFORMANCE_TAGS)", file=sys.stderr)
        return script

    base_words = spoken_words(script)
    prompt = PERFORMANCE_PROMPT + script
    problem = ""
    for attempt in (1, 2):
        try:
            raw = run_opencode(prompt, f"Morning podcast performance {TODAY:%Y-%m-%d}",
                               timeout=180)
            dropped = [t for t in TAG_RE.findall(raw)
                       if normalize_tag(t) not in ALLOWED_TAGS]
            tagged = trim_preamble(sanitize_tags(raw), script)
            if dropped:
                print(f"dropped unsupported tags: {', '.join(dropped)}", file=sys.stderr)
        except RuntimeError as e:
            problem = str(e)
            print(f"performance pass {attempt} failed: {e}", file=sys.stderr)
            if "timed out" in problem:
                break
            continue

        tags = TAG_RE.findall(tagged)
        words = spoken_words(tagged)
        if len(tags) > 4:
            problem = f"{len(tags)} non-verbal tags is too busy"
        elif not 0.97 <= words / base_words <= 1.03:
            problem = f"word count drifted from {base_words} to {words}"
        elif text_similarity(tagged, script) < 0.97:
            problem = "the words changed (this pass may only add non-verbal sounds)"
        elif not starts_with_script(tagged, script):
            problem = "the reply starts with a preamble, not the script"
        else:
            print(f"performance tags: {len(tags)} — {', '.join(tags) if tags else 'none'}",
                  file=sys.stderr)
            return tagged
        print(f"performance pass {attempt} rejected: {problem}", file=sys.stderr)
        prompt = PERFORMANCE_PROMPT + script + (
            f"\n\nYour previous attempt was rejected ({problem}). Add only the supported "
            "non-verbal tags, change no words, and reply with only the tagged script — no "
            "preamble or commentary."
        )

    print(f"keeping the untagged script for VoiceStudio: {problem}", file=sys.stderr)
    return script


def main():
    data = {"date": TODAY.strftime("%A %d %B %Y"), "weather_melbourne": weather(),
            "recent_greetings": recent_greetings(), "dashboard": dashboard_summary()}
    try:
        script = run_opencode(PROMPT + json.dumps(data, indent=1, ensure_ascii=False),
                              f"Morning podcast {TODAY:%Y-%m-%d}")
    except RuntimeError as e:
        sys.exit(str(e))

    tagged = performance_pass(script)

    out_dir = os.path.join(ROOT, "podcast")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"script-{TODAY:%Y-%m-%d}.txt")
    tagged_path = os.path.join(out_dir, f"script-{TODAY:%Y-%m-%d}.tagged.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(script + "\n")
    with open(tagged_path, "w", encoding="utf-8") as f:
        f.write(tagged + "\n")
    print(tagged)
    print(f"\n[{path}]  {spoken_words(script)} words  |  "
          f"[{tagged_path}]  {len(TAG_RE.findall(tagged))} non-verbal tag(s)", file=sys.stderr)


if __name__ == "__main__":
    main()
