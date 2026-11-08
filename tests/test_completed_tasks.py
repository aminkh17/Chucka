import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import generate_dashboard as dashboard
import generate_podcast_script as podcast


class CompletedTasksTests(unittest.TestCase):
    def test_only_explicit_dated_completions_count(self):
        with tempfile.TemporaryDirectory() as vault:
            note = Path(vault, "Projects", "Chucka", "Tasks.md")
            note.parent.mkdir(parents=True)
            note.write_text(
                "- [x] Ship **voice** #write ✅ 2026-10-23\n"
                "  - [X] Nested win completed:: 2026-10-23\n"
                "* [x] Review done:: 2026-10-23\n"
                "+ [x] Publish completion:: 2026-10-23\n"
                "- [ ] Still open ✅ 2026-10-23\n"
                "- [-] Cancelled ✅ 2026-10-23\n"
                "- [x] No completion date 📅 2026-10-23\n"
                "- [x] Old work ✅ 2026-10-22\n"
                "- [x] Today's work ✅ 2026-10-24\n"
                "- [x] Bad date ✅ 2026-99-99\n"
                "```markdown\n- [x] Example ✅ 2026-10-23\n```\n"
                "~~~\n- [x] Another example ✅ 2026-10-23\n~~~\n",
                encoding="utf-8",
            )
            hidden = Path(vault, ".trash")
            hidden.mkdir()
            (hidden / "Old.md").write_text("- [x] Trashed ✅ 2026-10-23\n")
            with patch.object(dashboard, "VAULT", vault):
                rows = dashboard.load_completed_tasks(dt.date(2026, 10, 23))
            self.assertEqual([r["task"] for r in rows],
                             ["Ship voice", "Nested win", "Review", "Publish"])
            self.assertTrue(all(r["project"] == "Chucka" for r in rows))
            self.assertTrue(all(r["completed_date"] == "2026-10-23" for r in rows))
            self.assertEqual(rows[0]["source"], "Projects/Chucka/Tasks.md")
            self.assertEqual(rows[0]["line"], 1)

    def test_git_history_detects_undated_completions(self):
        import os, subprocess
        with tempfile.TemporaryDirectory() as vault:
            note = Path(vault, "Projects", "Chucka", "Tasks.md")
            note.parent.mkdir(parents=True)

            def commit(body, when):
                note.write_text(body, encoding="utf-8")
                env = {**os.environ, "GIT_AUTHOR_DATE": when, "GIT_COMMITTER_DATE": when,
                       "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                       "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
                subprocess.run(["git", "-C", vault, "add", "-A"], check=True, env=env)
                subprocess.run(["git", "-C", vault, "commit", "-qm", "backup"], check=True, env=env)

            subprocess.run(["git", "init", "-q", vault], check=True)
            commit("- [ ] Ship it\n- [x] Old win\n- [ ] Later\n", "2026-10-22T20:00:00")
            commit("- [x] Ship it\n- [x] Old win moved\n- [ ] Later\n- [x] Quick fix\n",
                   "2026-10-23T12:00:00")
            commit("- [x] Ship it\n- [x] Old win moved\n- [x] Later\n- [x] Quick fix\n",
                   "2026-10-24T09:00:00")
            with patch.object(dashboard, "VAULT", vault):
                rows = dashboard.load_completed_tasks(dt.date(2026, 10, 23))
            self.assertIn("Ship it", [r["task"] for r in rows])
            self.assertIn("Quick fix", [r["task"] for r in rows])
            self.assertNotIn("Later", [r["task"] for r in rows])
            self.assertTrue(all(r["project"] == "Chucka" for r in rows))

    def test_calendar_yesterday_including_year_boundary(self):
        with tempfile.TemporaryDirectory() as root:
            with patch.multiple(podcast, ROOT=root, TODAY=dt.date(2027, 1, 1)), \
                 patch.object(podcast, "load_jobs", return_value=([], [], None)), \
                 patch.object(podcast, "load_projects", return_value=[]), \
                 patch.object(podcast, "load_tasks", return_value=(
                     {"learn": [], "write": [], "review": [], "other": []}, 0)), \
                 patch.object(podcast, "load_completed_tasks", return_value=[]) as completed:
                summary = podcast.dashboard_summary()
            completed.assert_called_once_with(dt.date(2026, 12, 31))
            self.assertEqual(summary["yesterday"],
                             {"date": "2026-12-31", "completed_tasks": []})

    def test_cached_priorities_still_read_completions_live(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as vault:
            out = Path(root, "out")
            out.mkdir()
            (out / "priorities-2026-10-24.json").write_text(json.dumps({
                "top3": [], "jobs": [], "projects": [],
                "tasks": {"learn": [], "write": [], "review": [], "other": []},
            }))
            Path(vault, "Work.md").write_text("- [x] Shipped ✅ 2026-10-23\n")
            with patch.multiple(podcast, ROOT=root, TODAY=dt.date(2026, 10, 24)), \
                 patch.object(dashboard, "VAULT", vault), \
                 patch.object(podcast, "load_jobs", return_value=([], [], None)), \
                 patch.object(podcast, "load_projects", return_value=[]), \
                 patch.object(podcast, "load_tasks", return_value=({}, 0)):
                summary = podcast.dashboard_summary()
            self.assertEqual(summary["yesterday"]["completed_tasks"][0]["task"], "Shipped")

    def test_wins_reach_script_and_performance_pass_without_sending(self):
        wins = {"yesterday": {"date": "2026-10-23", "completed_tasks": [
            {"task": "Ship voice update", "completed_date": "2026-10-23"}]}}
        script = "G'day, Amin! Yesterday you shipped the voice update. Today, focus on your Top 3."
        with tempfile.TemporaryDirectory() as root:
            with patch.multiple(podcast, ROOT=root, TODAY=dt.date(2026, 10, 24)), \
                 patch.object(podcast, "weather", return_value={}), \
                 patch.object(podcast, "recent_greetings", return_value=[]), \
                 patch.object(podcast, "dashboard_summary", return_value=wins), \
                 patch.object(podcast, "run_opencode", return_value=script) as generate, \
                 patch.object(podcast, "performance_pass", return_value=script) as performance, \
                 patch("builtins.print"):
                podcast.main()
            prompt = generate.call_args.args[0]
            data = json.loads(prompt[len(podcast.PROMPT):])
            self.assertEqual(data["dashboard"], wins)
            self.assertIn("Yesterday's wins FIRST", prompt)
            performance.assert_called_once_with(script)
            for suffix in (".txt", ".tagged.txt"):
                self.assertEqual(Path(root, "podcast", "script-2026-10-24" + suffix).read_text(),
                                 script + "\n")


if __name__ == "__main__":
    unittest.main()
