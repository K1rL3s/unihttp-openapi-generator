"""Coverage for the pipeline check helper and CLI error/version paths."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from unihttp_openapi_generator import __version__
from unihttp_openapi_generator.cli import app
from unihttp_openapi_generator.pipeline import CheckError, _mypy_args, _run_check

runner = CliRunner()


def test_run_check_reports_the_tool_output(tmp_path: Path) -> None:
    script = "print('boom'); raise SystemExit(1)"
    with pytest.raises(CheckError, match="boom"):
        _run_check("ruff", [sys.executable, "-c", script], tmp_path)


def test_mypy_args_omit_python_executable_without_a_separate_venv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    assert "--python-executable" not in _mypy_args()


def test_mypy_args_target_a_separate_activated_venv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "unihttp_openapi_generator.pipeline.target_python_executable",
        lambda: "/proj/.venv/bin/python",
    )
    assert _mypy_args()[-2:] == ["--python-executable", "/proj/.venv/bin/python"]


def test_version_flag() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


def test_invalid_package_name_is_bad_parameter(tmp_path: Path) -> None:
    # ``merge_settings`` succeeds (all required keys present) but ``GeneratorConfig``
    # rejects the package name -> the CLI turns the ValueError into a BadParameter.
    result = runner.invoke(
        app,
        ["generate", "spec.yaml", "-o", str(tmp_path), "--package-name", "not an identifier"],
    )
    assert result.exit_code != 0
    # the pydantic ValidationError (a ValueError) is surfaced as a BadParameter
    assert "Invalid value" in result.output
    assert "GeneratorConfig" in result.output
