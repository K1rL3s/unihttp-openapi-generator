"""Compile-gate: generated packages are deterministic and pass ruff + mypy --strict."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from unihttp_openapi_generator.config import ClientKind, FileLayout, GeneratorConfig, Serializer
from unihttp_openapi_generator.pipeline import run_generation

_MATRIX = [
    (Serializer.ADAPTIX, ClientKind.BOTH),
    (Serializer.PYDANTIC, ClientKind.SYNC),
    (Serializer.MSGSPEC, ClientKind.ASYNC),
]


@pytest.fixture
def spec_file(sample_spec: dict[str, Any], tmp_path: Path) -> Path:
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(sample_spec))
    return path


@pytest.fixture
def hierarchy_spec_file(hierarchy_spec: dict[str, Any], tmp_path: Path) -> Path:
    path = tmp_path / "hierarchy.json"
    path.write_text(json.dumps(hierarchy_spec))
    return path


def _collect_sources(root: Path) -> dict[str, str]:
    return {str(p.relative_to(root)): p.read_text() for p in sorted(root.rglob("*.py"))}


def _assert_ruff_clean(package_dir: Path) -> None:
    ruff = shutil.which("ruff")
    assert ruff is not None
    result = subprocess.run([ruff, "check", str(package_dir)], capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def _assert_mypy_strict_clean(package_dir: Path) -> None:
    # Run mypy via the current interpreter so it resolves imports (e.g. msgspec)
    # from this environment, not whatever bare ``mypy`` happens to be on PATH.
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "mypy",
            "--strict",
            "--disable-error-code",
            "no-untyped-call",
            "--explicit-package-bases",
            str(package_dir),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(("serializer", "client"), _MATRIX)
def test_generated_package_passes_ruff_and_mypy(
    spec_file: Path, tmp_path: Path, serializer: Serializer, client: ClientKind
) -> None:
    package = f"gate_{serializer.value}"
    out = tmp_path / package
    run_generation(
        str(spec_file),
        GeneratorConfig(package_name=package, output_dir=out, serializer=serializer, client=client),
    )
    _assert_ruff_clean(out / package)
    _assert_mypy_strict_clean(out / package)


@pytest.mark.parametrize("layout", list(FileLayout))
@pytest.mark.parametrize(("serializer", "client"), _MATRIX)
def test_inheritance_package_passes_ruff_and_mypy(
    hierarchy_spec_file: Path,
    tmp_path: Path,
    serializer: Serializer,
    client: ClientKind,
    layout: FileLayout,
) -> None:
    """``--inheritance`` emits a package that still survives ``--check``.

    A subclass declaration is where a wrong IR turns into an ``[assignment]`` error
    rather than a slightly-off annotation, and the unit tests reason about the IR, not
    about what mypy makes of the rendered classes. Both layouts run because the base
    class is the one reference that has to be imported at *runtime* in the per-object
    layout, not deferred into the ``TYPE_CHECKING`` block.
    """
    package = f"inh_{serializer.value}_{layout.name.lower()}"
    out = tmp_path / package
    run_generation(
        str(hierarchy_spec_file),
        GeneratorConfig(
            package_name=package,
            output_dir=out,
            serializer=serializer,
            client=client,
            file_layout=layout,
            inheritance=True,
        ),
    )
    _assert_ruff_clean(out / package)
    _assert_mypy_strict_clean(out / package)


def test_generation_is_deterministic(spec_file: Path, tmp_path: Path) -> None:
    config_a = GeneratorConfig(package_name="det_client", output_dir=tmp_path / "a")
    config_b = GeneratorConfig(package_name="det_client", output_dir=tmp_path / "b")
    run_generation(str(spec_file), config_a)
    run_generation(str(spec_file), config_b)
    sources_a = _collect_sources(tmp_path / "a" / "det_client")
    sources_b = _collect_sources(tmp_path / "b" / "det_client")
    assert sources_a == sources_b
