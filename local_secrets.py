"""Read local development secrets without committing them to the repository.

Environment variables take precedence over the ignored project-root
``.env.local`` file. The parser intentionally supports only KEY=value lines,
comments, and optional single/double quotes; no third-party dotenv package is
needed.
"""

import os
from pathlib import Path


_ENV_FILE = Path(__file__).resolve().with_name(".env.local")
_CACHE = None


def _read_local_file():
    values = {}
    try:
        lines = _ENV_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return values

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip()
        if value[:1] in {"'", '"'} and value[-1:] == value[:1]:
            value = value[1:-1]
        if name:
            values[name] = value
    return values


def get_secret(name, default=""):
    """Get a secret from the process environment or ignored ``.env.local``."""
    environment_value = os.environ.get(name)
    if environment_value:
        return environment_value

    global _CACHE
    if _CACHE is None:
        _CACHE = _read_local_file()
    return _CACHE.get(name, default)
