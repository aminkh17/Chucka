#!/usr/bin/env python3
"""Priority ranking — the single source of truth for what matters on the board.

Every job, project and task gets a score from signals already present in the
vault, then a band within its lane:

    P1  do first in that lane
    P2  next up
    P3  later

The three P1s — best job, best project, best task — are the day's Top 3, so the
dashboard image and the voice note share one ranking.

Manual override: put #p1 / #p2 / #p3 on a task line, use Obsidian Tasks flags
(🔺/⏫ = P1, 🔼 = P2, 🔽/⏬ = P3), or `priority:: 1|2|3` on its own line in a
project note. Tasks can also carry a due date (📅 2026-11-10). Explicit beats
computed, in ordering and in banding.
"""
import re
import datetime as dt

PRIORITY_TAG = re.compile(r"#p([123])\b", re.IGNORECASE)
# Obsidian Tasks flags: highest/high -> P1, medium -> P2, low/lowest -> P3
PRIORITY_EMOJI = re.compile(r"🔺|⏫|🔼|🔽|⏬")
_EMOJI_MAP = {"🔺": "P1", "⏫": "P1", "🔼": "P2", "🔽": "P3", "⏬": "P3"}
# standalone line only — inline examples in notes must not become overrides
PRIORITY_FIELD = re.compile(r"(?im)^\s*(?:[-*]\s+)?priority\s*::\s*(high|medium|low|[123])\s*$")
_FIELD_MAP = {"high": "P1", "medium": "P2", "low": "P3",
              "1": "P1", "2": "P2", "3": "P3"}

# explicit tags move items in the ordering: forced P1 to the top, forced P3 down
_ORDER_BONUS = {"P1": 1000, "P2": 0, "P3": -1000}

LANE_LABEL = {"learn": "Study queue", "write": "Writing", "review": "Review"}

_DUE_PATTERNS = (
    re.compile(r"(?im)^\s*(?:[-*]\s+)?(?:due|deadline)\s*::?\s*(\d{4}-\d{2}-\d{2})\s*$"),
    re.compile(r"(?im)^\s*(?:[-*]\s+)?📅\s*(\d{4}-\d{2}-\d{2})\s*$"),
)


def parse_due(text):
    """Deadline from a note: `due:: 2026-10-25`, `deadline:: ...` or `📅 2026-10-25`."""
    for pattern in _DUE_PATTERNS:
        m = pattern.search(text or "")
        if m:
            try:
                return dt.date(*map(int, m.group(1).split("-")))
            except ValueError:
                return None
    return None


_TASK_DUE_PATTERNS = (
    re.compile(r"📅\s*(\d{4}-\d{2}-\d{2})"),
    re.compile(r"(?:due|deadline)\s*::?\s*(\d{4}-\d{2}-\d{2})", re.IGNORECASE),
)


def parse_task_due(text):
    """Due date from an Obsidian Tasks line: `📅 2026-11-10` or `due:: 2026-11-10`."""
    for pattern in _TASK_DUE_PATTERNS:
        m = pattern.search(text or "")
        if m:
            try:
                return dt.date(*map(int, m.group(1).split("-")))
            except ValueError:
                return None
    return None


def explicit_priority(*parts):
    blob = " ".join(p for p in parts if p)
    m = PRIORITY_TAG.search(blob)
    if m:
        return f"P{m.group(1)}"
    m = PRIORITY_EMOJI.search(blob)
    if m:
        return _EMOJI_MAP[m.group(0)]
    m = PRIORITY_FIELD.search(blob)
    return _FIELD_MAP.get(m.group(1).lower()) if m else None


def priority_field(text):
    """Project override: `priority:: 1|2|3|high|medium|low` on its own line in the note."""
    m = PRIORITY_FIELD.search(text or "")
    return _FIELD_MAP.get(m.group(1).lower()) if m else None


def _score(n):
    # no upper cap: a deadline can (and should) outrank everything else
    return max(0, round(n))


def job_score(job, today):
    stage = (job.get("stage") or "").lower()
    score = 10
    for key, pts in (("offer", 60), ("interview", 55), ("application", 35),
                     ("screening", 30), ("recruiter", 20)):
        if key in stage:
            score = pts
            break
    score += {"HOT": 20, "WARM": 10}.get((job.get("temp") or "").upper(), 0)
    last = job.get("last")
    if last:
        days = (today - last).days
        # an ageing conversation needs a nudge more than a fresh one
        score += 0 if days <= 2 else 6 if days <= 6 else 12 if days <= 13 else 20
    if job.get("next"):
        score += 4
    return _score(score)


def project_score(project, today):
    score = 10
    if project.get("status", "").startswith("Next:"):
        score += 30           # it has a concrete next action
    score += min(project.get("open", 0), 6) * 4
    days = (today - project["updated"]).days
    score += 20 if days <= 2 else 14 if days <= 7 else 8 if days <= 14 else 3 if days <= 30 else 0
    due = project.get("due")
    if due:
        # a deadline is the strongest signal a project can carry
        left = (due - today).days
        score += (60 if left < 0 else 55 if left == 0 else 45 if left <= 2
                  else 32 if left <= 7 else 20 if left <= 14 else 10 if left <= 30 else 0)
    return _score(score)


_TASK_TAGS = {"interview": 30, "job": 30, "apply": 25, "write": 18, "review": 14,
              "study": 10, "learn": 10, "omni": 6, "idea": 4}
_URGENT = re.compile(r"\b(today|tonight|now|urgent|asap|due|deadline|tomorrow)\b", re.IGNORECASE)
_PROJECT_BONUS = {"P1": 25, "P2": 12, "P3": 0}


def _project_of(source):
    """Task source path -> project name, for priority inheritance."""
    m = re.match(r"Projects/([^/]+)/", source or "")
    return m.group(1) if m else None


def task_score(task, today, project_priorities):
    raw = task.get("raw", "")
    tags = {t.lower() for t in re.findall(r"#(\w+)", raw)}
    score = 5 + sum(pts for tag, pts in _TASK_TAGS.items() if tag in tags)
    if _URGENT.search(raw):
        score += 30
    project = _project_of(task.get("source"))
    score += _PROJECT_BONUS.get(project_priorities.get(project), 0)
    mtime = task.get("mtime")
    if mtime:
        days = (today - mtime).days
        score += 8 if days <= 2 else 4 if days <= 7 else 0
    due = task.get("due")
    if due:
        # same urgency curve as projects
        left = (due - today).days
        score += (60 if left < 0 else 55 if left == 0 else 45 if left <= 2
                  else 32 if left <= 7 else 20 if left <= 14 else 10 if left <= 30 else 0)
    return _score(score)


def _urgency(due, today):
    """Deadline pressure: 2 = overdue/due today, 1 = due within two days, else 0."""
    if not due:
        return 0
    left = (due - today).days
    return 2 if left <= 0 else 1 if left <= 2 else 0


def _order(item):
    # an urgent deadline outranks a flag; an explicit #p3 still sinks to the bottom
    demoted = -1 if item.get("explicit") == "P3" else 0
    return (demoted, item.get("urgency", 0),
            item["score"] + _ORDER_BONUS.get(item.get("explicit"), 0))


def _band(items, cuts):
    """P1 for the first `cuts[0]`, P2 up to `cuts[1]`, P3 after — flags and deadlines lift."""
    for i, item in enumerate(items):
        rank = "P1" if i < cuts[0] else "P2" if i < cuts[1] else "P3"
        explicit = item.get("explicit")
        urgent = item.get("urgency", 0)
        if explicit == "P3":
            band = "P3"
        elif explicit == "P1" or urgent == 2:
            band = "P1"
        elif (explicit == "P2" or urgent == 1) and rank == "P3":
            band = "P2"
        else:
            band = rank
        item["priority"] = band


def rank_jobs(jobs, today):
    items = [dict(j, score=job_score(j, today),
                  explicit=explicit_priority(j.get("company"), j.get("role"), j.get("next")))
             for j in jobs]
    items.sort(key=_order, reverse=True)
    _band(items, (1, 3))
    return items


def rank_projects(projects, today):
    items = [dict(p, score=project_score(p, today),
                  urgency=_urgency(p.get("due"), today),
                  explicit=p.get("explicit") or explicit_priority(p.get("name"), p.get("status")))
             for p in projects]
    items.sort(key=_order, reverse=True)
    _band(items, (1, 3))
    return items


def rank_tasks(tasks, today, project_priorities):
    ranked = {}
    for name, items in tasks.items():
        rows = [dict(t, score=task_score(t, today, project_priorities),
                     urgency=_urgency(t.get("due"), today),
                     explicit=explicit_priority(t.get("raw")))
                for t in items]
        for row in rows:
            row["queue"] = name
        rows.sort(key=_order, reverse=True)
        ranked[name] = rows
    flat = sorted((t for rows in ranked.values() for t in rows), key=_order, reverse=True)
    _band(flat, (1, 4))
    return ranked, flat


def _task_context(task):
    """Queue and project for the voice/PNG, e.g. 'Writing • Chucka' or just 'Magic'."""
    parts = [LANE_LABEL.get(task.get("queue"), ""), task.get("project")]
    return " • ".join(p for p in parts if p) or "Inbox"


def build_top3(jobs, projects, tasks, today):
    """One P1 per lane — the morning rule: 1 submit • 1 code • 1 study."""
    top = []
    if jobs:
        j = jobs[0]
        top.append({"lane": "JOB", "title": f"{j['company']}: {j['stage']}",
                    "action": j.get("next") or "", "priority": j["priority"],
                    "score": j["score"],
                    "age": (today - j["last"]).days if j.get("last") else None})
    if projects:
        p = projects[0]
        status = p.get("status", "")
        due = p.get("due")
        top.append({"lane": "PROJECT", "title": p["name"],
                    "action": status[6:] if status.startswith("Next:") else status,
                    "priority": p["priority"], "score": p["score"],
                    "age": (today - p["updated"]).days,
                    "due": f"{due:%d %b}" if due else None,
                    "due_days": (due - today).days if due else None})
    if tasks:
        t = tasks[0]
        due = t.get("due")
        top.append({"lane": "TASK", "title": t["text"],
                    "action": _task_context(t),
                    "priority": t["priority"], "score": t["score"], "age": None,
                    "due": f"{due:%d %b}" if due else None,
                    "due_days": (due - today).days if due else None})
    if len(top) < 3:
        used = {t["title"] for t in top}
        rest = []
        for lane, items in (("JOB", jobs), ("PROJECT", projects), ("TASK", tasks)):
            for it in items:
                title = (f"{it['company']}: {it['stage']}" if lane == "JOB"
                         else it.get("name") or it.get("text"))
                if title in used:
                    continue
                due = it.get("due")
                action = (_task_context(it) if lane == "TASK"
                          else it.get("next") or it.get("status") or "")
                rest.append({"lane": lane, "title": title,
                             "action": action,
                             "priority": it["priority"], "score": it["score"], "age": None,
                             "due": f"{due:%d %b}" if due else None,
                             "due_days": (due - today).days if due else None})
        rest.sort(key=lambda x: x["score"], reverse=True)
        top += rest[: 3 - len(top)]
    return top[:3]


def build_payload(jobs, projects, tasks, today):
    """Everything the PNG and the voice need, ranked once."""
    ranked_jobs = rank_jobs(jobs, today)
    ranked_projects = rank_projects(projects, today)
    project_priorities = {p["name"]: p["priority"] for p in ranked_projects}
    ranked_tasks, flat_tasks = rank_tasks(tasks, today, project_priorities)
    return {
        "date": today.isoformat(),
        "top3": build_top3(ranked_jobs, ranked_projects, flat_tasks, today),
        "jobs": ranked_jobs,
        "projects": ranked_projects,
        "tasks": ranked_tasks,
    }
