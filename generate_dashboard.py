#!/usr/bin/env python3
"""Morning Dashboard: read the Obsidian vault live and render a 1080x1920 PNG."""
import json, os, re, sys, glob, datetime as dt
from PIL import Image, ImageDraw, ImageFont

import envload; envload.load_env()  # noqa: E402
from priority import build_payload, parse_due, priority_field  # noqa: E402

VAULT = os.environ.get("VAULT", "")
OUT_DIR = os.environ.get("OUT_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "out"))
TODAY = dt.date.today()

def read(rel):
    try:
        with open(os.path.join(VAULT, rel), encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""

def mdate(path):
    return dt.date.fromtimestamp(os.path.getmtime(path))

def clean(s):
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)
    s = re.sub(r"\[\[([^\]|]*)(\|[^\]]*)?\]\]", r"\1", s)
    s = re.sub(r"[*`]", "", s)
    s = re.sub(r"https?://\S+", "", s)
    s = re.sub(r"[^\u0000-\u024F\u2010-\u2027\u2190-\u21FF]", "", s)
    return re.sub(r"\s+", " ", s).strip()

def parse_date(s):
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    return dt.date(*map(int, m.groups())) if m else None

# ---------- data ----------
def load_jobs():
    text = read("Job Hunting/2026 Job hunt.md")
    jobs, closed = [], []
    updated = parse_date(re.search(r"updated (\d{4}-\d{2}-\d{2})", text).group(1)) if re.search(r"updated (\d{4}-\d{2}-\d{2})", text) else None
    header = None
    for line in text.splitlines():
        if not line.startswith("|"):
            if header and jobs:
                header = None if line.strip() else header
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if header is None:
            if "Company" in cells:
                header = [c.lower() for c in cells]
            continue
        if set("".join(cells)) <= set("-: "):
            continue
        row = dict(zip(header, cells))
        jobs.append({
            "company": clean(row.get("company", "")),
            "role": clean(row.get("role", "")),
            "stage": clean(row.get("stage", "")),
            "last": parse_date(row.get("last activity", "")),
            "temp": clean(row.get("temperature", "")).upper() or "?",
            "next": clean(row.get("next move", "")),
        })
    m = re.search(r"#### Closed(.*?)(\n#{1,3} |\Z)", text, re.S)
    if m:
        for line in m.group(1).splitlines():
            b = re.match(r"-\s+\*\*(.+?)\*\*", line.strip())
            if b:
                closed.append(clean(b.group(1)).split(" (")[0].split(" — ")[0])
    return jobs, closed, updated

def stage_rank(stage):
    s = stage.lower()
    for i, key in enumerate(["offer", "interview", "application", "recruiter", "screening"]):
        if key in s:
            return i
    return 9

def load_projects():
    projs = []
    for d in sorted(glob.glob(os.path.join(VAULT, "Projects", "*/"))):
        name = clean(os.path.basename(d.rstrip("/")))
        files = glob.glob(os.path.join(d, "**", "*.md"), recursive=True)
        if not files:
            continue
        latest = max(files, key=os.path.getmtime)
        body = "\n".join(read(os.path.relpath(f, VAULT)) for f in files)
        open_t = re.findall(r"^\s*- \[ \] (.+)$", body, re.M)
        done_t = re.findall(r"^\s*- \[x\] (.+)$", body, re.M | re.I)
        status = ""
        sm = re.search(r"(?im)^\s*[-*]?\s*\**(stage|status)\**\s*(?:::|:|—)\s*(.+)$", body)
        if sm:
            status = clean(sm.group(2))
        elif open_t:
            status = "Next: " + clean(open_t[0])
        else:
            status = "Idea / notes"
        project_meta = "\n".join(l for l in body.splitlines()
                                 if not re.match(r"^\s*- \[[ xX]\]", l))
        projs.append({"name": name, "status": status, "open": len(open_t), "done": len(done_t),
                      "updated": mdate(latest), "explicit": priority_field(body),
                      "due": parse_due(project_meta)})
    projs.sort(key=lambda p: p["updated"], reverse=True)
    return projs

def load_tasks():
    tagged = {"learn": [], "write": [], "review": [], "other": []}
    total = 0
    for f in glob.glob(os.path.join(VAULT, "**", "*.md"), recursive=True):
        if "/." in f:
            continue
        for line in open(f, encoding="utf-8", errors="ignore"):
            m = re.match(r"^- \[ \] (.+)$", line.rstrip())  # top-level open tasks only
            if not m:
                continue
            total += 1
            raw = m.group(1)
            tags = {t.lower() for t in re.findall(r"#(\w+)", raw)}
            text = clean(re.sub(r"#\w+", "", raw)).strip(" -,") or clean(raw)
            item = {"text": text, "raw": raw,
                    "source": os.path.relpath(f, VAULT), "mtime": mdate(f)}
            if tags & {"study", "learn", "watch", "reading", "lookup", "localllm"}:
                tagged["learn"].append(item)
            elif "write" in tags:
                tagged["write"].append(item)
            elif "review" in tags:
                tagged["review"].append(item)
    return tagged, total

# ---------- drawing ----------
W, H = 1080, 1920
BG, NAVY, NAVY2, CARD = (241, 244, 248), (15, 31, 60), (24, 46, 88), (255, 255, 255)
INK, MUTED, LINE = (22, 30, 46), (100, 112, 135), (226, 232, 240)
RED, BLUE, PURPLE, TEAL, ORANGE = (225, 67, 67), (37, 99, 235), (124, 58, 237), (13, 148, 136), (234, 88, 12)
PRIO_COLORS = {"P1": RED, "P2": ORANGE, "P3": (148, 163, 184)}
ARIAL = "/System/Library/Fonts/Supplemental/Arial.ttf"
ARIAL_B = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"

def F(size, bold=False):
    try:
        return ImageFont.truetype(ARIAL_B if bold else ARIAL, size)
    except OSError:
        return ImageFont.load_default()

img = Image.new("RGB", (W, H), BG)
d = ImageDraw.Draw(img)
L, R = 32, W - 32
CW = R - L

def fit(text, font, maxw):
    if d.textlength(text, font=font) <= maxw:
        return text
    while text and d.textlength(text + "…", font=font) > maxw:
        text = text[:-1]
    return text.rstrip() + "…"

def label(x, y, text, color):
    f = F(20, True)
    w = d.textlength(text, font=f)
    d.rounded_rectangle([x, y, x + w + 28, y + 34], radius=17, fill=color)
    d.text((x + 14, y + 5), text, font=f, fill=(255, 255, 255))
    return w + 28

def card(y, h):
    d.rounded_rectangle([L, y, R, y + h], radius=24, fill=CARD, outline=LINE, width=2)

def days_ago(date):
    return (TODAY - date).days if date else None

def main():
    jobs, closed, jobs_updated = load_jobs()
    projects = load_projects()
    tasks, total_open = load_tasks()

    # Ranked once here, shared with the podcast generator through
    # out/priorities-<date>.json — the PNG and the voice can never disagree.
    payload = build_payload(jobs, projects, tasks, TODAY)
    jobs, projects, tasks = payload["jobs"], payload["projects"], payload["tasks"]
    active = jobs

    # header
    d.rectangle([0, 0, W, 270], fill=NAVY)
    d.rectangle([0, 0, W, 8], fill=(56, 189, 248))
    d.ellipse([880, -120, 1180, 180], fill=NAVY2)
    d.text((48, 36), "CHUCKA", font=F(50, True), fill=(255, 255, 255))
    d.text((48 + d.textlength("CHUCKA", font=F(50, True)) + 16, 60), "aka Morning Dashboard",
           font=F(26), fill=(148, 184, 226))
    d.text((48, 100), TODAY.strftime("%A  %d %b %Y") + "  •  Obsidian status → plan ahead", font=F(25), fill=(148, 184, 226))
    x = 48
    role_word = "ROLE" if len(jobs) == 1 else "ROLES"
    for text, col in [(f"{len(jobs)} ACTIVE {role_word}", (56, 189, 248)), (f"{len(projects)} PROJECTS", (167, 139, 250)),
                      (f"{total_open} OPEN TASKS", (110, 231, 183))]:
        f = F(21, True)
        pw = d.textlength(text, font=f) + 44
        d.rounded_rectangle([x, 152, x + pw, 194], radius=21, fill=(255, 255, 255))
        d.ellipse([x + 13, 168, x + 25, 180], fill=col)
        d.text((x + 31, 158), text, font=f, fill=NAVY)
        x += pw + 12
    src = f"Source: Obsidian vault  •  Job hunt {jobs_updated:%d %b}" if jobs_updated else "Source: Obsidian vault"
    if projects:
        src += f"  •  Latest project edit {projects[0]['updated']:%d %b}"
    d.text((48, 206), src, font=F(19), fill=(148, 184, 226))

    # top 3 — one P1 per lane (job, project, task), the morning rule
    y, h = 290, 330
    card(y, h)
    lw = label(L + 24, y + 16, "TODAY'S TOP 3  •  MUST-DO", RED)
    d.text((L + 24 + lw + 14, y + 22), "P1 do first  •  P2 next  •  P3 later", font=F(17), fill=MUTED)
    colors = [((254, 226, 226), RED), ((219, 234, 254), BLUE), ((254, 243, 199), ORANGE)]
    lane_colors = {"JOB": BLUE, "PROJECT": PURPLE, "TASK": TEAL}
    cy = y + 60
    for i, item in enumerate(payload["top3"]):
        bg, dot = colors[i % len(colors)]
        if item.get("due_days") is not None:
            left = item["due_days"]
            when = (("OVERDUE %dd" % abs(left)) if left < 0
                    else "DUE TODAY" if left == 0 else f"due {item['due']} ({left}d)")
            suffix = f"  •  {when}"
        else:
            age = item.get("age")
            suffix = f"  •  {age}d since update" if age is not None else ""
        d.rounded_rectangle([L + 20, cy, R - 20, cy + 80], radius=14, fill=bg)
        d.ellipse([L + 34, cy + 16, L + 46, cy + 28], fill=dot)
        d.text((L + 54, cy + 8), fit(f"{i + 1}  {item['title']}{suffix}", F(21, True), CW - 250),
               font=F(21, True), fill=INK)
        d.text((L + 54, cy + 40), fit(item.get("action") or "", F(20), CW - 250), font=F(20),
               fill=(55, 65, 90))
        pw = d.textlength(item["lane"], font=F(15, True)) + 22
        lx = R - 38 - pw
        d.rounded_rectangle([lx, cy + 30, lx + pw, cy + 54], radius=12,
                            fill=lane_colors.get(item["lane"], MUTED))
        d.text((lx + 11, cy + 33), item["lane"], font=F(15, True), fill=(255, 255, 255))
        cy += 88

    # job pipeline
    shown = active[:5]
    y, h = y + h + 16, 60 + 56 * max(1, len(shown)) + (36 if closed else 10)
    card(y, h)
    lw = label(L + 24, y + 16, f"JOB PIPELINE  •  {len(jobs)} ACTIVE", BLUE)
    d.text((L + 24 + lw + 12, y + 21), "Sorted by priority", font=F(19), fill=MUTED)
    cy = y + 60
    for i, j in enumerate(shown):
        warm = j["temp"] in ("WARM", "HOT")
        tcol = ORANGE if warm else (100, 116, 139)
        d.ellipse([L + 38, cy + 8, L + 50, cy + 20], fill=(34, 197, 94) if warm else (148, 163, 184))
        d.text((L + 58, cy + 1), fit(f"{j['company']} — {j['role']}", F(21, True), CW - 260), font=F(21, True), fill=INK)
        when = f"{j['last']:%d %b}" if j["last"] else "?"
        d.text((L + 58, cy + 26), fit(f"{j['stage']} • {when}", F(19), CW - 260), font=F(19), fill=MUTED)
        fp = F(17, True)
        tw = d.textlength(j["temp"], font=fp)
        px = R - 38 - tw - 22
        d.rounded_rectangle([px, cy + 6, px + tw + 22, cy + 34], radius=13, outline=tcol, width=2)
        d.text((px + 11, cy + 9), j["temp"], font=fp, fill=tcol)
        ppw = d.textlength(j["priority"], font=F(15, True)) + 20
        ppx = px - 10 - ppw
        d.rounded_rectangle([ppx, cy + 9, ppx + ppw, cy + 33], radius=12, fill=PRIO_COLORS[j["priority"]])
        d.text((ppx + 10, cy + 12), j["priority"], font=F(15, True), fill=(255, 255, 255))
        cy += 56
        if i < len(shown) - 1:
            d.line([L + 34, cy - 6, R - 34, cy - 6], fill=LINE, width=2)
    if closed:
        d.text((L + 38, cy + 2), fit("Closed: " + " • ".join(closed), F(18), CW - 80), font=F(18), fill=MUTED)

    # projects
    rest = projects[1:]
    rows = max(1, (len(rest) + 1) // 2)
    y, h = y + h + 16, 60 + (106 if projects else 0) + rows * 56 + 6
    card(y, h)
    label(L + 24, y + 16, f"PROJECTS  •  {len(projects)} TRACKED", PURPLE)
    cy = y + 60
    if projects:
        p = projects[0]
        if p.get("due"):
            left = (p["due"] - TODAY).days
            when = (("OVERDUE %dd" % abs(left)) if left < 0
                    else "due today" if left == 0 else f"due {p['due']:%d %b} ({left}d)")
            head = f"{p['name'].upper()} — {when}"
        else:
            head = f"{p['name'].upper()} — latest activity {p['updated']:%d %b}"
        d.rounded_rectangle([L + 20, cy, R - 20, cy + 96], radius=14, fill=(237, 233, 254))
        d.text((L + 38, cy + 8), fit(head, F(20, True), CW - 160), font=F(20, True), fill=(76, 29, 149))
        d.text((L + 38, cy + 36), fit(p["status"], F(19), CW - 80), font=F(19), fill=(76, 60, 120))
        d.text((L + 38, cy + 64), f"{p['done']} done • {p['open']} open", font=F(18), fill=(109, 88, 160))
        ppw = d.textlength(p["priority"], font=F(15, True)) + 20
        ppx = R - 38 - ppw
        d.rounded_rectangle([ppx, cy + 10, ppx + ppw, cy + 34], radius=12, fill=PRIO_COLORS[p["priority"]])
        d.text((ppx + 10, cy + 13), p["priority"], font=F(15, True), fill=(255, 255, 255))
        cy += 106
    cell_h = 48
    colw = (CW - 52) // 2
    for i, p in enumerate(rest):
        bx = L + 20 + (i % 2) * (colw + 12)
        by = cy + (i // 2) * (cell_h + 8)
        d.rounded_rectangle([bx, by, bx + colw, by + cell_h], radius=11, fill=(248, 250, 252), outline=LINE, width=2)
        psw = d.textlength(p["priority"], font=F(13, True)) + 14
        d.text((bx + 12, by + 4), fit(p["name"], F(19, True), colw - 34 - psw), font=F(19, True), fill=INK)
        d.rounded_rectangle([bx + colw - 10 - psw, by + 5, bx + colw - 10, by + 24], radius=9, fill=PRIO_COLORS[p["priority"]])
        d.text((bx + colw - 10 - psw + 7, by + 7), p["priority"], font=F(13, True), fill=(255, 255, 255))
        if cell_h >= 44:
            status = p["status"] + (f" • due {p['due']:%d %b}" if p.get("due") else "")
            d.text((bx + 12, by + 25), fit(status, F(17), colw - 24), font=F(17), fill=MUTED)

    # learn / write / review
    y, h = y + h + 16, 330
    card(y, h)
    label(L + 24, y + 16, "LEARN  •  WRITE  •  REVIEW", TEAL)
    cy = y + 60
    rx = L + CW // 2 + 8
    d.text((L + 38, cy), f"STUDY QUEUE ({len(tasks['learn'])})", font=F(19, True), fill=INK)
    d.text((rx, cy), f"WRITE ({len(tasks['write'])}) + REVIEW ({len(tasks['review'])})", font=F(19, True), fill=INK)
    cy += 28
    right = sorted(tasks["write"] + tasks["review"], key=lambda t: (t["priority"], -t["score"]))[:5]
    for i in range(5):
        if i < len(tasks["learn"]):
            t = tasks["learn"][i]
            d.text((L + 38, cy + i * 26), t["priority"], font=F(14, True), fill=PRIO_COLORS[t["priority"]])
            d.text((L + 64, cy + i * 26), fit("• " + t["text"], F(19), CW // 2 - 76), font=F(19), fill=(40, 55, 75))
        if i < len(right):
            t = right[i]
            d.text((rx, cy + i * 26), t["priority"], font=F(14, True), fill=PRIO_COLORS[t["priority"]])
            d.text((rx + 26, cy + i * 26), fit("• " + t["text"], F(19), CW // 2 - 76), font=F(19), fill=(40, 55, 75))
    by = y + h - 62
    d.rounded_rectangle([L + 20, by, R - 20, by + 46], radius=13, fill=NAVY)
    d.text((L + 38, by + 11), "Morning rule: 1 submit  •  1 code  •  1 study  •  pick 3 Must-Do", font=F(20, True), fill=(255, 255, 255))

    name = f"morning-dashboard-{TODAY:%Y-%m-%d}.png"
    d.text((48, H - 52), f"{name}  •  generated {dt.datetime.now():%H:%M} from Obsidian", font=F(19), fill=MUTED)

    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, name)
    img.save(out)
    with open(os.path.join(OUT_DIR, f"priorities-{TODAY:%Y-%m-%d}.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1, ensure_ascii=False, default=str)
    print(out)

if __name__ == "__main__":
    if not os.path.isdir(VAULT):
        sys.exit(f"Vault not found: {VAULT!r} — set VAULT in .env (copy .env.example to .env).")
    main()
