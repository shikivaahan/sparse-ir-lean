"""Pytest fixtures for the public-checkout test suite.

Fixture bodies re-use the same skip helpers exposed via
``tests._dataset_prereq`` so a single source of truth governs the
prerequisite check. The fixtures are useful when a test body itself wants
to skip a single case without skipping the whole module.
"""

from __future__ import annotations

import pytest

from tests._dataset_prereq import (
    has_ingested_problems,
    has_zebralogic_source,
)


@pytest.fixture(scope="session")
def zebralogic_source_available() -> bool:
    """True iff the external ZebraLogic source artifact is present on disk."""
    return has_zebralogic_source()


@pytest.fixture(scope="session")
def ingested_problems_available() -> bool:
    """True iff the regenerated ingested_problems directory is present."""
    return has_ingested_problems()