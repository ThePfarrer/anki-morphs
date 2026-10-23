from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import aqt.package
import pytest

from ankimorphs.morphemizers import python_binary
from ankimorphs.morphemizers.python_binary import get_python_binary


def test_launcher_build_uses_the_anki_venv(monkeypatch: pytest.MonkeyPatch) -> None:
    # anki 25.09 and earlier ran from a uv-managed venv
    launcher_python = "/home/user/.local/share/AnkiProgramFiles/.venv/bin/python"
    monkeypatch.setattr(
        aqt.package, "venv_binary", lambda cmd: launcher_python, raising=False
    )
    assert get_python_binary() == launcher_python


@pytest.mark.parametrize(
    "executable",
    [
        "/Applications/Anki.app/Contents/MacOS/Anki",
        "/usr/local/anki",
    ],
)
def test_self_contained_build_has_no_interpreter(
    monkeypatch: pytest.MonkeyPatch, executable: str
) -> None:
    # anki 26.08 removed venv_binary, and the official builds run from a
    # frozen binary we cannot create a venv with
    monkeypatch.delattr(aqt.package, "venv_binary", raising=False)
    monkeypatch.setattr(sys, "executable", executable)
    monkeypatch.setattr(
        "ankimorphs.morphemizers.python_binary._find_matching_external_python",
        lambda: None,
    )
    assert get_python_binary() is None


def test_self_contained_build_uses_matching_external_python(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delattr(aqt.package, "venv_binary", raising=False)
    monkeypatch.setattr(sys, "executable", "/Applications/Anki.app/Contents/MacOS/Anki")
    external = "/home/user/.local/share/uv/python/cpython-3.13.5/bin/python3"
    monkeypatch.setattr(
        "ankimorphs.morphemizers.python_binary._find_matching_external_python",
        lambda: external,
    )
    assert get_python_binary() == external


@pytest.mark.parametrize(
    "executable",
    [
        "/app/bin/python3.13",
        "/usr/bin/python3",
    ],
)
def test_python_based_install_uses_the_running_interpreter(
    monkeypatch: pytest.MonkeyPatch, executable: str
) -> None:
    monkeypatch.delattr(aqt.package, "venv_binary", raising=False)
    monkeypatch.setattr(sys, "executable", executable)
    assert get_python_binary() == executable


SAME_VERSION = (sys.version_info.major, sys.version_info.minor)
OTHER_VERSION = (SAME_VERSION[0], SAME_VERSION[1] + 1)


def _fake_run(
    versions: dict[str, tuple[int, int] | Exception],
) -> Callable[..., subprocess.CompletedProcess[str]]:
    """Returns a subprocess.run stand-in that reports a version per executable."""

    def run(cmd: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        outcome = versions[cmd[0]]
        if isinstance(outcome, Exception):
            raise outcome
        return subprocess.CompletedProcess(cmd, 0, stdout=f"{outcome}\n")

    return run


@pytest.fixture(name="isolated_search")
def fixture_isolated_search(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """No PATH hit, and uv's install dir pointed at an empty tmp dir."""
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    monkeypatch.setenv("UV_PYTHON_INSTALL_DIR", str(tmp_path))
    monkeypatch.setattr(os.path, "expanduser", lambda _p: "")
    monkeypatch.setattr(os.path, "expandvars", lambda _p: "")
    return tmp_path


def test_external_python_found_on_path(  # pylint: disable=unused-argument
    monkeypatch: pytest.MonkeyPatch, isolated_search: Path
) -> None:
    on_path = "/opt/homebrew/bin/python3.13"
    monkeypatch.setattr(shutil, "which", lambda _name: on_path)
    monkeypatch.setattr(subprocess, "run", _fake_run({on_path: SAME_VERSION}))
    assert python_binary._find_matching_external_python() == on_path


def test_external_python_found_in_uv_dir(
    monkeypatch: pytest.MonkeyPatch, isolated_search: Path
) -> None:
    uv_python = (
        isolated_search
        / f"cpython-{SAME_VERSION[0]}.{SAME_VERSION[1]}.5-macos-aarch64-none"
        / "bin"
        / "python3"
    )
    uv_python.parent.mkdir(parents=True)
    uv_python.touch()
    monkeypatch.setattr(subprocess, "run", _fake_run({str(uv_python): SAME_VERSION}))
    assert python_binary._find_matching_external_python() == str(uv_python)


def test_external_python_with_wrong_version_is_rejected(  # pylint: disable=unused-argument
    monkeypatch: pytest.MonkeyPatch, isolated_search: Path
) -> None:
    # e.g. a 'python3.13' shim that actually resolves to another version
    on_path = "/usr/local/bin/python3.13"
    monkeypatch.setattr(shutil, "which", lambda _name: on_path)
    monkeypatch.setattr(subprocess, "run", _fake_run({on_path: OTHER_VERSION}))
    assert python_binary._find_matching_external_python() is None


@pytest.mark.parametrize(
    "failure",
    [
        OSError("exec format error"),
        subprocess.CalledProcessError(1, "python"),
        subprocess.TimeoutExpired("python", 10),
    ],
)
def test_broken_external_python_is_skipped(  # pylint: disable=unused-argument
    monkeypatch: pytest.MonkeyPatch, isolated_search: Path, failure: Exception
) -> None:
    broken = "/usr/local/bin/python3.13"
    monkeypatch.setattr(shutil, "which", lambda _name: broken)
    monkeypatch.setattr(subprocess, "run", _fake_run({broken: failure}))
    assert python_binary._find_matching_external_python() is None


def test_no_external_python_available(  # pylint: disable=unused-argument
    isolated_search: Path,
) -> None:
    assert python_binary._find_matching_external_python() is None
