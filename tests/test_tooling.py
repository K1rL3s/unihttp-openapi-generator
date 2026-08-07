"""The generator must use the ruff/mypy installed with it, never a system copy."""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

import pytest

from unihttp_openapi_generator import tooling
from unihttp_openapi_generator.tooling import (
    ToolNotFoundError,
    mypy_command,
    ruff_executable,
    target_python_executable,
)


def _make_executable(directory: Path, name: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text("#!/bin/sh\n")
    path.chmod(0o755)
    return path


def test_prefers_own_environment_over_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The regression: a system ruff on PATH must not win over the co-installed one."""
    own = _make_executable(tmp_path / "venv" / "bin", "ruff")
    system = _make_executable(tmp_path / "usr" / "bin", "ruff")

    monkeypatch.setattr(sysconfig, "get_path", lambda *a, **kw: str(own.parent))
    monkeypatch.setattr(shutil, "which", lambda name: str(system))

    assert ruff_executable() == str(own)


def test_falls_back_to_path_when_env_has_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    system = _make_executable(tmp_path / "usr" / "bin", "ruff")
    monkeypatch.setattr(sysconfig, "get_path", lambda *a, **kw: str(tmp_path / "empty"))
    monkeypatch.setattr(sys, "executable", str(tmp_path / "empty" / "python"))
    monkeypatch.setattr(shutil, "which", lambda name: str(system))

    assert ruff_executable() == str(system)


def test_ruff_missing_everywhere_names_the_fix(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(sysconfig, "get_path", lambda *a, **kw: str(tmp_path / "empty"))
    # sys.executable's own directory is a candidate too, and the real one has ruff.
    monkeypatch.setattr(sys, "executable", str(tmp_path / "empty" / "python"))
    monkeypatch.setattr(shutil, "which", lambda name: None)

    with pytest.raises(ToolNotFoundError, match="force-reinstall"):
        ruff_executable()


def test_lookup_result_is_cached(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    own = _make_executable(tmp_path / "bin", "ruff")
    calls = 0

    def counting_get_path(*args: object, **kwargs: object) -> str:
        nonlocal calls
        calls += 1
        return str(own.parent)

    monkeypatch.setattr(sysconfig, "get_path", counting_get_path)
    ruff_executable()
    after_first = calls
    ruff_executable()
    assert calls == after_first


class TestInstallScriptsDir:
    """The generator's own install location tells us where its ruff landed."""

    @pytest.mark.parametrize(
        ("module_file", "expected"),
        [
            ("/env/lib/python3.12/site-packages/unihttp_openapi_generator/tooling.py", "/env/bin"),
            ("/usr/lib/python3/dist-packages/unihttp_openapi_generator/tooling.py", "/usr/bin"),
        ],
    )
    def test_derives_the_prefix_bin(
        self, monkeypatch: pytest.MonkeyPatch, module_file: str, expected: str
    ) -> None:
        monkeypatch.setattr(tooling, "__file__", module_file)
        assert tooling._install_scripts_dir() == expected

    def test_windows_layout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            tooling, "__file__", "/env/Lib/site-packages/unihttp_openapi_generator/tooling.py"
        )
        monkeypatch.setattr(os, "name", "nt")
        assert tooling._install_scripts_dir() == "/env/Scripts"

    def test_none_from_a_source_checkout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(tooling, "__file__", "/repo/src/unihttp_openapi_generator/tooling.py")
        assert tooling._install_scripts_dir() is None

    def test_beats_an_ambient_install_of_the_wrong_version(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A too-old system ruff sits in the default scripts dir; ours must still win."""
        own = _make_executable(tmp_path / "userbase" / "bin", "ruff")
        _make_executable(tmp_path / "usr" / "local" / "bin", "ruff")
        monkeypatch.setattr(
            tooling,
            "__file__",
            str(tmp_path / "userbase" / "lib" / "python3.12" / "site-packages")
            + "/unihttp_openapi_generator/tooling.py",
        )
        monkeypatch.setattr(
            sysconfig, "get_path", lambda *a, **kw: str(tmp_path / "usr" / "local" / "bin")
        )

        assert ruff_executable() == str(own)


def test_script_dirs_survive_a_missing_sys_executable(monkeypatch: pytest.MonkeyPatch) -> None:
    """A frozen/embedded interpreter reports no executable; lookup must not crash."""
    monkeypatch.setattr(sys, "executable", "")
    assert "" not in tooling._script_dirs()


def test_script_dirs_are_deduplicated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sysconfig, "get_path", lambda *a, **kw: "/same/bin")
    monkeypatch.setattr(sys, "executable", "/same/bin/python")
    assert tooling._script_dirs() == ["/same/bin"]


def test_mypy_runs_through_this_interpreter() -> None:
    assert mypy_command() == [sys.executable, "-m", "mypy"]


def test_mypy_command_actually_runs() -> None:
    result = subprocess.run([*mypy_command(), "--version"], capture_output=True, text=True)
    assert result.returncode == 0
    assert result.stdout.startswith("mypy ")


def test_mypy_missing_names_the_fix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    with pytest.raises(ToolNotFoundError, match="force-reinstall"):
        mypy_command()


class TestTargetPython:
    """``--check`` resolves the generated package's imports against the user's venv."""

    def test_none_without_an_activated_venv(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("VIRTUAL_ENV", raising=False)
        assert target_python_executable() is None

    def test_none_when_the_venv_is_the_generator_s_own(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("VIRTUAL_ENV", sys.prefix)
        assert target_python_executable() is None

    def test_points_at_a_different_activated_venv(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        bindir = "Scripts" if os.name == "nt" else "bin"
        python = _make_executable(tmp_path / "proj" / bindir, "python")
        monkeypatch.setenv("VIRTUAL_ENV", str(tmp_path / "proj"))

        assert target_python_executable() == str(python)

    def test_none_when_the_venv_path_is_stale(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("VIRTUAL_ENV", str(tmp_path / "deleted"))
        assert target_python_executable() is None
