"""Load and integrity-check the pinned ZebraLogicBench Stage 0 subset.

This module validates dataset provenance and layout only. It does not parse clues,
check solutions, or make any correctness decision.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATASET_ROOT = REPOSITORY_ROOT / "tests" / "dataset_zebra"
DATASET_LAYOUT_VERSION = "0.1.0"


@dataclass(frozen=True)
class ZebraRecord:
    external_id: str
    grid: str
    houses: int
    categories: int
    split: str
    path: Path
    puzzle: str
    raw: dict[str, Any]


@dataclass(frozen=True)
class DatasetManifest:
    layout_version: str
    source_dataset: str
    source_revision: str
    records: tuple[ZebraRecord, ...]


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _require_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string")
    return value


def load_zebra_subset(root: Path = DEFAULT_DATASET_ROOT) -> DatasetManifest:
    root = root.resolve()
    manifest_data = _read_json(root / "manifest.json")
    layout_version = _require_string(manifest_data.get("layout_version"), "layout_version")
    if layout_version != DATASET_LAYOUT_VERSION:
        raise ValueError(
            f"unsupported dataset layout {layout_version!r}; expected {DATASET_LAYOUT_VERSION!r}"
        )

    source = manifest_data.get("source")
    if not isinstance(source, dict):
        raise ValueError("source must be an object")
    source_dataset = _require_string(source.get("dataset"), "source.dataset")
    source_revision = _require_string(source.get("revision"), "source.revision")

    entries = manifest_data.get("records")
    if not isinstance(entries, list) or not entries:
        raise ValueError("records must be a non-empty array")

    records: list[ZebraRecord] = []
    seen_ids: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("each manifest record must be an object")
        external_id = _require_string(entry.get("external_id"), "external_id")
        if external_id in seen_ids:
            raise ValueError(f"duplicate external_id: {external_id}")
        seen_ids.add(external_id)

        grid = _require_string(entry.get("grid"), "grid")
        grid_parts = grid.split("x")
        if len(grid_parts) != 2 or not all(part.isdigit() for part in grid_parts):
            raise ValueError(f"invalid grid: {grid}")
        houses, categories = (int(part) for part in grid_parts)

        relative_path = Path(_require_string(entry.get("path"), "path"))
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError(f"record path must stay inside dataset root: {relative_path}")
        record_path = root / relative_path
        raw_bytes = record_path.read_bytes()
        actual_hash = hashlib.sha256(raw_bytes).hexdigest()
        expected_hash = _require_string(entry.get("sha256"), "sha256")
        if actual_hash != expected_hash:
            raise ValueError(f"checksum mismatch: {relative_path}")

        raw = json.loads(raw_bytes)
        if not isinstance(raw, dict):
            raise ValueError(f"record must be a JSON object: {relative_path}")
        if raw.get("id") != external_id:
            raise ValueError(f"external ID mismatch: {relative_path}")
        if raw.get("size") != grid.replace("x", "*"):
            raise ValueError(f"grid metadata mismatch: {relative_path}")
        puzzle = _require_string(raw.get("puzzle"), f"{external_id}.puzzle")

        records.append(
            ZebraRecord(
                external_id=external_id,
                grid=grid,
                houses=houses,
                categories=categories,
                split=_require_string(entry.get("split"), "split"),
                path=record_path,
                puzzle=puzzle,
                raw=raw,
            )
        )

    return DatasetManifest(
        layout_version=layout_version,
        source_dataset=source_dataset,
        source_revision=source_revision,
        records=tuple(records),
    )


def main() -> int:
    manifest = load_zebra_subset()
    grids = ", ".join(sorted({record.grid for record in manifest.records}))
    print(
        f"loaded {len(manifest.records)} records from {manifest.source_dataset} "
        f"at {manifest.source_revision}; grids: {grids}"
    )
    return 0
