"""Locate the ruff/mypy that ship with the generator, not whatever is on ``PATH``.

``ruff`` and ``mypy`` are declared dependencies, so installing the generator installs
them into the generator's own environment. That environment's script directory is not
necessarily on ``PATH``: ``uv tool install`` and ``pipx`` expose only the console
scripts a distribution declares, so ``shutil.which("ruff")`` reaches past the pinned
copy and finds an unrelated system install -- a different version, formatting the
generated code by different rules -- or nothing at all.

Every lookup here therefore starts from the interpreter running the generator and only
falls back to ``PATH`` as a last resort.
"""

from __future__ import annotations

import functools
import importlib.util
import os
import shutil
import sys
import sysconfig


class ToolNotFoundError(Exception):
    """Raised when a tool the generator depends on cannot be located."""


def _install_scripts_dir() -> str | None:
    """Scripts directory of the environment *this module* is installed into.

    Searched first, because ruff arrived through the same install as the generator.
    ``sysconfig``'s default scheme cannot stand in for this: under ``pip install
    --user`` it names the system ``bin`` while the generator and its ruff live under
    the user scheme, so a too-old system ruff would win. Returns ``None`` from a source
    checkout, where the module does not sit under ``site-packages`` at all.
    """
    site_packages = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if os.path.basename(site_packages) not in ("site-packages", "dist-packages"):
        return None
    if os.name == "nt":  # <prefix>/Lib/site-packages -> <prefix>/Scripts
        return os.path.join(os.path.dirname(os.path.dirname(site_packages)), "Scripts")
    # <prefix>/lib/python3.X/site-packages -> <prefix>/bin
    prefix = os.path.dirname(os.path.dirname(os.path.dirname(site_packages)))
    return os.path.join(prefix, "bin")


def _script_dirs() -> list[str]:
    """Script directories to search, own-environment first, ambient last."""
    candidates = [
        # Where the generator itself was installed -- ruff came from the same install.
        _install_scripts_dir(),
        # The active environment (inside a venv, its ``bin``/``Scripts``).
        sysconfig.get_path("scripts"),
        # Alongside the interpreter itself, for layouts sysconfig describes oddly.
        os.path.dirname(sys.executable) if sys.executable else "",
        # ``pip install --user`` puts scripts in the user scheme, e.g. ``~/.local/bin``.
        sysconfig.get_path("scripts", scheme=sysconfig.get_preferred_scheme("user")),
        # The base interpreter, for a venv created with ``--system-site-packages``.
        sysconfig.get_path("scripts", vars={"base": sys.base_prefix}),
    ]
    unique: list[str] = []
    for directory in candidates:
        if directory and directory not in unique:
            unique.append(directory)
    return unique


def _find_executable(name: str) -> str | None:
    exe = name + (sysconfig.get_config_var("EXE") or "")
    for directory in _script_dirs():
        candidate = os.path.join(directory, exe)
        if os.path.isfile(candidate):
            return candidate
    return shutil.which(name)


@functools.cache
def ruff_executable() -> str:
    """Absolute path to ruff, preferring the copy installed with the generator."""
    found = _find_executable("ruff")
    if found is None:
        raise ToolNotFoundError(
            "ruff was not found. It is a dependency of unihttp-openapi-generator, so "
            "reinstalling the generator restores it: "
            "pip install --force-reinstall unihttp-openapi-generator"
        )
    return found


def mypy_command() -> list[str]:
    """Command prefix that runs the mypy installed with the generator.

    ``python -m mypy`` rather than a resolved script path, because the interpreter is
    also what mypy resolves the checked package's imports against by default.
    """
    if importlib.util.find_spec("mypy") is None:
        raise ToolNotFoundError(
            "mypy was not found. It is a dependency of unihttp-openapi-generator, so "
            "reinstalling the generator restores it: "
            "pip install --force-reinstall unihttp-openapi-generator"
        )
    return [sys.executable, "-m", "mypy"]


def target_python_executable() -> str | None:
    """The interpreter whose site-packages the *generated* code should resolve against.

    ``--check`` type-checks generated code that imports unihttp and the chosen
    serializer. Those live in the user's project environment, which is a different
    environment from the generator's whenever the generator was installed as a
    standalone tool. When an activated virtualenv says so, point mypy at it; otherwise
    the interpreter running the generator is already the right answer.
    """
    venv = os.environ.get("VIRTUAL_ENV")
    if not venv:
        return None
    # Compare environment roots, not the interpreters: two venvs built from the same
    # base python have ``bin/python`` symlinks that resolve to one shared binary, so
    # ``samefile`` would call distinct environments identical.
    if os.path.normpath(venv) == os.path.normpath(sys.prefix):
        return None
    bindir = "Scripts" if os.name == "nt" else "bin"
    exe = os.path.join(venv, bindir, "python" + (sysconfig.get_config_var("EXE") or ""))
    return exe if os.path.isfile(exe) else None
