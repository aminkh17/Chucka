import unittest
from types import SimpleNamespace
from unittest.mock import patch

import generate_podcast_script as podcast


class PodcastModelTests(unittest.TestCase):
    def test_no_override_uses_opencode_default_for_both_passes(self):
        for title in ("Morning podcast", "Morning podcast performance"):
            with self.subTest(title=title), patch.object(podcast, "MODEL", ""), \
                 patch.object(podcast.subprocess, "run", return_value=SimpleNamespace(
                     returncode=0, stdout="The script", stderr="")) as run:
                self.assertEqual(podcast.run_opencode("Write a script", title), "The script")
                run.assert_called_once_with(
                    [podcast.OPENCODE, "run", "--auto", "--title", title, "Write a script"],
                    capture_output=True, text=True, timeout=300, cwd=podcast.ROOT,
                )

    def test_explicit_override_is_preserved(self):
        with patch.object(podcast, "MODEL", "provider/custom-model"), \
             patch.object(podcast.subprocess, "run", return_value=SimpleNamespace(
                 returncode=0, stdout="The script", stderr="")) as run:
            podcast.run_opencode("Write a script", "Morning podcast")
            cmd = run.call_args.args[0]
            self.assertEqual(cmd[cmd.index("--model") + 1], "provider/custom-model")


if __name__ == "__main__":
    unittest.main()
