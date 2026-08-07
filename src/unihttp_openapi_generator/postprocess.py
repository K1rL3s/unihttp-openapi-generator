"""Post-process generated source: format and sort imports with ruff."""

from __future__ import annotations

import subprocess
from pathlib import Path

from unihttp_openapi_generator.tooling import ruff_executable


class PostProcessError(Exception):
    """Raised when an external formatter/checker fails."""


def _run(args: list[str], source: str, *, filename: str) -> str:
    result = subprocess.run(
        [ruff_executable(), *args, "--stdin-filename", filename, "-"],
        input=source,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise PostProcessError(
            f"ruff {' '.join(args)} failed for {filename}:\n{result.stderr or result.stdout}"
        )
    return result.stdout


def format_python(source: str, *, filename: str = "generated.py") -> str:
    """Sort imports, drop unused imports, then format the given source."""
    fixed = _run(
        ["check", "--select", "I,F401", "--fix", "--quiet"],
        source,
        filename=filename,
    )
    return _run(["format", "--quiet"], fixed, filename=filename)


def format_path(path: Path) -> None:
    """Run ruff import-sorting and formatting over files on disk (project-aware)."""
    target = str(path)
    fix = subprocess.run(
        [ruff_executable(), "check", "--select", "I,F401", "--fix", "--quiet", target],
        capture_output=True,
        text=True,
    )
    if fix.returncode not in (0, 1):  # 1 == remaining lint findings, acceptable here
        raise PostProcessError(f"ruff check failed for {target}:\n{fix.stderr or fix.stdout}")
    fmt = subprocess.run(
        [ruff_executable(), "format", "--quiet", target],
        capture_output=True,
        text=True,
    )
    if fmt.returncode != 0:
        raise PostProcessError(f"ruff format failed for {target}:\n{fmt.stderr or fmt.stdout}")
