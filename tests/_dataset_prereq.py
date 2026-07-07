"""Dataset prerequisite skip helpers for the public-checkout test suite.

The public repository intentionally omits:

* ``data/zebralogic/source.json`` (external ZebraLogic source artifact)
* ``eval/gates/stage2_gate_a_compile_all/ingested_problems/*.problem.json``
  (regenerated from the external source)

Test modules that genuinely depend on these artifacts must call
``require_zebralogic_source()`` or ``require_ingested_problems()`` at module
load time so the module skips cleanly on a public clone instead of failing
collection. Gate scripts (under ``scripts/``) continue to fail loudly when
invoked without their required input; this module only governs pytest.
"""

from __future__ import annotations

from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]

ZEBRALOGIC_SOURCE_PATH = REPO_ROOT / "data" / "zebralogic" / "source.json"
INGESTED_PROBLEMS_DIR = (
    REPO_ROOT / "eval" / "gates" / "stage2_gate_a_compile_all" / "ingested_problems"
)

SKIP_ZEBRALOGIC_SOURCE_REASON = (
    "requires external ZebraLogic source artifact: "
    f"{ZEBRALOGIC_SOURCE_PATH.relative_to(REPO_ROOT).as_posix()}"
)
SKIP_INGESTED_PROBLEMS_REASON = (
    "requires ingested problem artifacts under "
    f"{INGESTED_PROBLEMS_DIR.relative_to(REPO_ROOT).as_posix()} "
    "(regenerate from the external ZebraLogic source via "
    "scripts/stage2_gate_a_compile_all.py before running dataset-backed gates)"
)


def has_zebralogic_source() -> bool:
    return ZEBRALOGIC_SOURCE_PATH.exists()


def has_ingested_problems() -> bool:
    return INGESTED_PROBLEMS_DIR.is_dir() and any(
        INGESTED_PROBLEMS_DIR.glob("*.problem.json")
    )


def require_zebralogic_source() -> None:
    """Skip the importing module if the external source artifact is missing."""
    if not has_zebralogic_source():
        pytest.skip(SKIP_ZEBRALOGIC_SOURCE_REASON, allow_module_level=True)


def require_ingested_problems() -> None:
    """Skip the importing module if ingested_problems is missing on disk."""
    if not has_ingested_problems():
        pytest.skip(SKIP_INGESTED_PROBLEMS_REASON, allow_module_level=True)