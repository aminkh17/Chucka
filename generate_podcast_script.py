#!/usr/bin/env python3
"""Generate the spoken podcast script for the morning dashboard via the opencode CLI."""
import datetime as dt
import glob
import json
import os
import re
import subprocess
import sys
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from generate_dashboard import load_jobs, load_projects, load_tasks, clean  # noqa: E402
from priority import build_payload  # noqa: E402

import envload; envload.load_env()  # noqa: E402

VAULT = os.environ.get("VAULT", "")
MODEL = os.environ.get("PODCAST_MODEL", "opencode/deepseek-v4.1-flash-free")
OPENCODE = os.environ.get("OPENCODE_BIN", "/opt/homebrew/bin/opencode")
WEATHER_URL = "https://wttr.in/Melbourne?format=j1"
TODAY = dt.date.today()


import ssl

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
    for p in sorted(glob.glob(os.path.join(ROOT, "podcast", "script-*.txt")), reverse=True):
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
        "study": task_rows(ranked["tasks"]["learn"]),
        "writing": task_rows(ranked["tasks"]["write"]),
        "reviews": task_rows(ranked["tasks"]["review"]),
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
3. Explain the morning dashboard clearly, in this order:
   - "top3": the three must-dos for today — one job, one project, one task. They are
     already ranked: follow their exact order and explain why each one matters
   - how many active job roles there are and the single most important next action
   - the state of the projects, naming only the two or three that need attention; if one
     has a deadline, say whether it is overdue, due today, or how many days are left
   - what is in the study queue and what writing is waiting, including any due dates
4. Close with one motivating sentence. This closing line is required, always include it.

Rules:
- 45 to 70 seconds when spoken: roughly 120 to 180 words, no more.
- Plain spoken sentences. No markdown, no bullet points, no URLs, no emoji, no stage directions —
  with one exception: the delivery tags below.
- Delivery tags: the voice engine understands exactly two inline tags, [laughter] and [sigh].
  Use them at most twice per script, and only where they genuinely fit — a light [laughter] for
  something wry, a dry [sigh] after a stalled item. Most days, zero or one is right. Never invent
  any other bracketed tag: anything else in brackets would be spoken aloud literally.
- Rhythm comes from punctuation: short sentences, commas and dashes for pauses.
- Delivery energy: a bright breakfast-radio brief — short, punchy sentences, upbeat verbs, the
  odd exclamation where it fits. Never flat or sleepy.
- Never read non-English names of companies letter by letter; say them naturally.
- Do not invent facts that are not in the data. If something is unknown, leave it out.
- Priority: every item in the DATA carries a "priority" — P1 (do first), P2 (next), P3
  (later). The "top3" list is authoritative: never reorder it or promote something else.
- Address Amin directly as "you".
- Output only the script text.

DATA
----
"""


def run_opencode(prompt):
    cmd = [OPENCODE, "run", "--model", MODEL, "--auto", "--title",
           f"Morning podcast {TODAY:%Y-%m-%d}", prompt]
    # cwd matters under launchd, which starts the job in "/": opencode picks up project context from it.
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=300, cwd=ROOT)
    if p.returncode != 0:
        sys.exit(f"opencode failed ({p.returncode}): {p.stderr[-1500:]}")
    text = p.stdout.strip()
    text = re.sub(r"^```[a-z]*\n|\n```$", "", text).strip()
    if not text:
        sys.exit("opencode returned no text")
    return text


def main():
    data = {"date": TODAY.strftime("%A %d %B %Y"), "weather_melbourne": weather(),
            "recent_greetings": recent_greetings(), "dashboard": dashboard_summary()}
    script = run_opencode(PROMPT + json.dumps(data, indent=1, ensure_ascii=False))

    out_dir = os.path.join(ROOT, "podcast")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"script-{TODAY:%Y-%m-%d}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(script + "\n")
    print(script)
    print(f"\n[{path}]  {len(script.split())} words", file=sys.stderr)


if __name__ == "__main__":
    main()
