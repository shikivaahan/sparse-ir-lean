from pathlib import Path

import pytest

from sparseir_harness.dataset import load_zebra_subset


def test_real_subset_loads_across_grid_sizes() -> None:
    manifest = load_zebra_subset()

    assert manifest.layout_version == "0.1.0"
    assert manifest.source_dataset == "allenai/ZebraLogicBench"
    assert manifest.source_revision == "a909ef550df0d218775ea6fc950368db34c98680"
    assert {record.grid for record in manifest.records} == {"2x2", "4x4", "6x6"}
    assert {record.external_id for record in manifest.records} == {
        "lgp-test-2x2-33",
        "lgp-test-4x4-27",
        "lgp-test-6x6-5",
    }
    assert all(record.split == "test" for record in manifest.records)
    assert all(record.puzzle.startswith("There are ") for record in manifest.records)


def test_loader_rejects_tampered_record(tmp_path: Path) -> None:
    source_root = Path(__file__).parent / "dataset_zebra"
    target_root = tmp_path / "dataset_zebra"
    target_root.mkdir()
    (target_root / "manifest.json").write_bytes((source_root / "manifest.json").read_bytes())
    for grid in ("2x2", "4x4", "6x6"):
        (target_root / grid).mkdir()
        for source in (source_root / grid).glob("*.json"):
            (target_root / grid / source.name).write_bytes(source.read_bytes())

    record = target_root / "2x2" / "lgp-test-2x2-33.json"
    record.write_text(record.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="checksum mismatch"):
        load_zebra_subset(target_root)
