from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys
from pathlib import Path


def get_python_binary() -> str | None:
    """
    Returns a python interpreter that can bootstrap the spaCy/CAMeL venvs,
    or None if no suitable one can be found.

    Anki 25.09 and earlier ran from a uv-managed venv and exposed its python
    through 'aqt.package.venv_binary'. Anki 26.05 replaced the launcher with
    briefcase packaging, and 26.08 removed that function, so we fall back to
    the interpreter anki itself is running on. The official 26.x builds are
    self-contained apps where sys.executable is the anki binary instead of a
    python interpreter, so as a last resort we look for an external interpreter
    with the same major.minor version as anki's embedded python, because the
    venv's site-packages are imported into anki's process and contain compiled
    extensions that must match.
    """
    try:
        # pylint:disable=import-outside-toplevel
        from aqt.package import venv_binary
    except ImportError:
        pass
    else:
        launcher_python: str | None = venv_binary("python")
        if launcher_python is not None:
            return launcher_python

    # we can't run sys.executable to determine whether it is a python
    # interpreter, because doing that on a self-contained build launches
    # another anki instance
    if Path(sys.executable).name.lower().startswith("python"):
        return sys.executable

    return _find_matching_external_python()


def _find_matching_external_python() -> str | None:
    major, minor = sys.version_info.major, sys.version_info.minor
    version = f"{major}.{minor}"

    candidates: list[str] = []
    on_path = shutil.which(f"python{version}")
    if on_path is not None:
        candidates.append(on_path)

    # uv-managed interpreters, e.g. installed with 'uv python install 3.13'
    uv_dirs = [
        os.environ.get("UV_PYTHON_INSTALL_DIR", ""),
        os.path.expanduser("~/.local/share/uv/python"),
        os.path.expandvars(r"%APPDATA%\uv\python"),
    ]
    for uv_dir in filter(None, uv_dirs):
        candidates += sorted(
            glob.glob(os.path.join(uv_dir, f"cpython-{version}.*", "bin", "python3"))
        )
        candidates += sorted(
            glob.glob(os.path.join(uv_dir, f"cpython-{version}.*", "python.exe"))
        )

    for candidate in candidates:
        try:
            result = subprocess.run(
                [candidate, "-c", "import sys; print(sys.version_info[:2])"],
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if result.stdout.strip() == f"({major}, {minor})":
            return candidate

    return None
