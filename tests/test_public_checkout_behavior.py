"""Public-checkout pytest behaviour regression checks.

These tests pin the contract that the ordinary pytest collection is green
on a clean public clone. They assert the skip helpers exist and point at
the right artifact paths, and that the shared fixtures report the
expected status on the current checkout.
"""

from __future__ import annotations

from tests._dataset_prereq import (
    INGESTED_PROBLEMS_DIR,
    REPO_ROOT,
    SKIP_INGESTED_PROBLEMS_REASON,
    SKIP_ZEBRALOGIC_SOURCE_REASON,
    ZEBRALOGIC_SOURCE_PATH,
    has_ingested_problems,
    has_zebralogic_source,
)


def test_skip_helpers_point_at_canonical_paths() -> None:
    assert ZEBRALOGIC_SOURCE_PATH == REPO_ROOT / "data" / "zebralogic" / "source.json"
    assert INGESTED_PROBLEMS_DIR == (
        REPO_ROOT / "eval" / "gates" / "stage2_gate_a_compile_all" / "ingested_problems"
    )
    assert "data/zebralogic/source.json" in SKIP_ZEBRALOGIC_SOURCE_REASON
    assert "ingested_problems" in SKIP_INGESTED_PROBLEMS_REASON


def test_zebralogic_source_artifact_is_intentionally_absent_on_public_clone() -> None:
    """The public tree must NOT commit the external ZebraLogic source artifact.

    If this test fails the artifact was committed by mistake, which would
    silently couple the public tree to a pinned third-party dataset.
    """
    assert not has_zebralogic_source(), (
        f"unexpectedly found {ZEBRALOGIC_SOURCE_PATH} on the public checkout"
    )


def test_ingested_problems_is_intentionally_absent_on_public_clone() -> None:
    """The public tree must NOT commit the regenerated ingested_problems tree."""
    assert not has_ingested_problems(), (
        f"unexpectedly found ingested_problems under {INGESTED_PROBLEMS_DIR}"
    )


def test_dataset_skip_reasons_are_documented_and_actionable() -> None:
    assert SKIP_ZEBRALOGIC_SOURCE_REASON.startswith(
        "requires external ZebraLogic source artifact:"
    )
    assert "data/zebralogic/source.json" in SKIP_ZEBRALOGIC_SOURCE_REASON
    assert SKIP_INGESTED_PROBLEMS_REASON.startswith(
        "requires ingested problem artifacts under"
    )
    # Researchers reading the skip must be told how to regenerate inputs.
    assert "scripts/stage2_gate_a_compile_all.py" in SKIP_INGESTED_PROBLEMS_REASON