#!/usr/bin/env python3
"""
One-command, cross-platform launcher for Buy or Wait?.

    python bootstrap.py [args passed through to code/main.py]

What it does (stdlib only, so it works with any Python >= 3.10 on macOS, Linux, Windows):
  1. Verifies the interpreter meets the minimum version.
  2. Creates an isolated virtual environment at ./.venv if missing.
  3. Installs the exact pinned dependencies from code/requirements.lock.txt
     (only when the lock file changed since the last install).
  4. Runs code/main.py inside that venv, forwarding all arguments.

Re-running is cheap: steps 2-3 are skipped once the venv is up to date.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import venv
from pathlib import Path

MIN_PYTHON = (3, 10)
ROOT = Path(__file__).resolve().parent
VENV_DIR = ROOT / ".venv"
LOCK_FILE = ROOT / "code" / "requirements.lock.txt"
STAMP_FILE = VENV_DIR / ".lock-sha256"
ENTRY = ROOT / "code" / "main.py"


def venv_python() -> Path:
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def check_python_version() -> None:
    if sys.version_info < MIN_PYTHON:
        need = ".".join(map(str, MIN_PYTHON))
        have = ".".join(map(str, sys.version_info[:3]))
        sys.exit(f"Buy or Wait? needs Python >= {need}; you are running {have}.")


def ensure_venv() -> Path:
    py = venv_python()
    if not py.exists():
        print(f"[bootstrap] creating virtual environment at {VENV_DIR}")
        venv.EnvBuilder(with_pip=True, clear=False).create(VENV_DIR)
    return py


def lock_digest() -> str:
    return hashlib.sha256(LOCK_FILE.read_bytes()).hexdigest()


def ensure_dependencies(py: Path) -> None:
    digest = lock_digest()
    if STAMP_FILE.exists() and STAMP_FILE.read_text().strip() == digest:
        return
    print(f"[bootstrap] installing pinned dependencies from {LOCK_FILE.relative_to(ROOT)}")
    subprocess.run(
        [str(py), "-m", "pip", "install", "--quiet", "--disable-pip-version-check",
         "-r", str(LOCK_FILE)],
        check=True,
    )
    STAMP_FILE.write_text(digest)


def main() -> int:
    check_python_version()
    py = ensure_venv()
    ensure_dependencies(py)
    cmd = [str(py), str(ENTRY), *sys.argv[1:]]
    return subprocess.run(cmd, cwd=ROOT).returncode


if __name__ == "__main__":
    sys.exit(main())
