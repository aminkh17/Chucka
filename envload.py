"""Load project .env values into os.environ (existing variables win).

Plain KEY=VALUE lines, '#' comments and blank lines are ignored. Values may be
optionally quoted. This keeps personal configuration (vault path, phone number,
binaries, API keys) out of the source files.
"""
import os


def load_env(path=None):
    path = path or os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    except OSError:
        pass
