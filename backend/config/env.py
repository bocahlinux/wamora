"""Local-development .env loading — a narrow ergonomics fix, not an
architecture change (see docs/generated/PHASE-7-ENV-LOADING-FIX-REPORT.md
for the repository-evidence review behind this).

Docker/production are unaffected: `backend/.dockerignore` already
excludes `.env` from the image, and both docker-compose files already
inject configuration via `env_file:` directly into the container
process's environment — neither path ever calls this function against a
present file. This exists solely so a bare `python manage.py ...`
invocation on a developer's machine picks up `backend/.env` the way
README.md's own documented steps already assumed it would.
"""

from pathlib import Path


def load_env_file(path: Path) -> None:
    """Loads KEY=VALUE pairs from `path` into os.environ, without
    overriding a variable that's already set in the real environment
    (matches python-dotenv's own default: override=False) — an operator
    who has explicitly exported/injected a value always wins over the
    file. Silently does nothing if `path` doesn't exist; never raises for
    a missing file, since that's the expected, normal case in Docker/
    production."""
    if not path.exists():
        return
    from dotenv import load_dotenv

    load_dotenv(path, override=False)


__all__ = ['load_env_file']
