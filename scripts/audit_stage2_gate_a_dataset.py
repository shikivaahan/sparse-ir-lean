#!/usr/bin/env python3
"""Audit Stage 2 Gate A source, ingestion, compilation, and review artifacts."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sparseir_harness.zebralogic_ingest import (
    DATASET_ID,
    SourceRecord,
    canonical_record_sha256,
    file_sha256,
    load_official_source,
)


AUDIT_NAME = "stage2_gate_a_dataset_audit"
EXPECTED_GATE_NAME = "stage2_gate_a_compile_all"
ORDINALS = {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth", 6: "sixth"}
ORDINAL_VALUES = {value: key for key, value in ORDINALS.items()}
SOURCE_RELATIONS = (
    (" is directly left of ", "direct_left"),
    (" is directly right of ", "direct_right"),
    (" is somewhere to the left of ", "left_of"),
    (" is somewhere to the right of ", "right_of"),
)


def _independent_surface(category: str, value: str) -> str:
    """Render one upstream template without using the ingestion implementation table."""
    fixed: dict[str, dict[str, str]] = {
        "Nationality": {
            "brit": "the british person",
            "chinese": "the chinese",
            "dane": "the dane",
            "german": "the german",
            "norwegian": "the norwegian",
            "swede": "the swedish person",
        },
        "Birthday": {
            "april": "the person whose birthday is in april",
            "feb": "the person whose birthday is in february",
            "jan": "the person whose birthday is in january",
            "mar": "the person whose birthday is in march",
            "may": "the person whose birthday is in may",
            "sept": "the person whose birthday is in september",
        },
        "Flower": {
            "carnations": "the person who loves a carnations arrangement",
            "daffodils": "the person who loves a bouquet of daffodils",
            "iris": "the person who loves the boquet of iris",
            "lilies": "the person who loves the boquet of lilies",
            "roses": "the person who loves the rose bouquet",
            "tulips": "the person who loves the vase of tulips",
        },
        "Animal": {
            "bird": "the bird keeper",
            "cat": "the cat lover",
            "dog": "the dog owner",
            "fish": "the fish enthusiast",
            "horse": "the person who keeps horses",
            "rabbit": "the rabbit owner",
        },
        "Food": {
            "grilled cheese": "the person who loves eating grilled cheese",
            "pizza": "the person who is a pizza lover",
            "soup": "the person who loves the soup",
            "spaghetti": "the person who loves the spaghetti eater",
            "stew": "the person who loves the stew",
            "stir fry": "the person who loves stir fry",
        },
        "Vacation": {
            "beach": "the person who loves beach vacations",
            "camping": "the person who enjoys camping trips",
            "city": "the person who prefers city breaks",
            "cruise": "the person who likes going on cruises",
            "cultural": "the person who goes on cultural tours",
            "mountain": "the person who enjoys mountain retreats",
        },
        "Smoothie": {
            "blueberry": "the person who drinks blueberry smoothies",
            "cherry": "the person who likes cherry smoothies",
            "desert": "the desert smoothie lover",
            "dragonfruit": "the dragonfruit smoothie lover",
            "lime": "the person who drinks lime smoothies",
            "watermelon": "the watermelon smoothie lover",
        },
        "Color": {
            "blue": "the person who loves blue",
            "green": "the person whose favorite color is green",
            "purple": "the person who loves purple",
            "red": "the person whose favorite color is red",
            "white": "the person who loves white",
            "yellow": "the person who loves yellow",
        },
        "Cigar": {
            "blends": "the person who smokes many unique blends",
            "blue master": "the person who smokes blue master",
            "dunhill": "the dunhill smoker",
            "pall mall": "the person partial to pall mall",
            "prince": "the prince smoker",
            "yellow monster": "the person who smokes yellow monster",
        },
        "HouseStyle": {
            "colonial": "the person living in a colonial-style house",
            "craftsman": "the person in a craftsman-style house",
            "mediterranean": "the person in a mediterranean-style villa",
            "modern": "the person in a modern-style house",
            "ranch": "the person in a ranch-style home",
            "victorian": "the person residing in a victorian house",
        },
        "Drink": {
            "boba tea": "the boba tea drinker",
            "coffee": "the coffee drinker",
            "milk": "the person who likes milk",
            "root beer": "the root beer lover",
            "tea": "the tea drinker",
            "water": "the one who only drinks water",
        },
        "Hobby": {
            "cooking": "the person who loves cooking",
            "gardening": "the person who enjoys gardening",
            "knitting": "the person who enjoys knitting",
            "painting": "the person who paints as a hobby",
            "photography": "the photography enthusiast",
            "woodworking": "the woodworking hobbyist",
        },
        "Pet": {
            "bird": "the person who keeps a pet bird",
            "cat": "the person who has a cat",
            "dog": "the person who owns a dog",
            "fish": "the person with an aquarium of fish",
            "hamster": "the person with a pet hamster",
            "rabbit": "the person who owns a rabbit",
        },
        "Education": {
            "associate": "the person with an associate's degree",
            "bachelor": "the person with a bachelor's degree",
            "doctorate": "the person with a doctorate",
            "high school": "the person with a high school diploma",
            "master": "the person with a master's degree",
            "trade school": "the person who attended trade school",
        },
    }
    if category == "Name":
        return value.lower()
    if category in fixed:
        return fixed[category][value]
    if category == "BookGenre":
        return f"the person who loves {value} books"
    if category == "Occupation":
        article = "an" if value in {"artist", "engineer"} else "a"
        return f"the person who is {article} {value}"
    if category == "Height":
        return "the person who has an average height" if value == "average" else f"the person who is {value}"
    if category == "HairColor":
        return f"the person who has {value} hair"
    if category == "MusicGenre":
        return f"the person who loves {value.replace('hip hop', 'hip-hop')} music"
    if category == "Mother":
        return f"the person whose mother's name is {value.lower()}"
    if category == "PhoneModel":
        article = "an" if value == "iphone 13" else "a"
        return f"the person who uses {article} {value}"
    if category == "FavoriteSport":
        return f"the person who loves {value}"
    if category == "CarModel":
        return f"the person who owns a {value.replace('ford f150', 'ford f-150')}"
    if category == "Children":
        if value == "Timothy":
            return "the person who is the mother of timothy"
        return f"the person's child is named {value.lower()}"
    raise ValueError(f"unsupported source category/value: {category}.{value}")


def _source_surface_map(categories: dict[str, list[str]]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for category, values in categories.items():
        for value in values:
            surface = _independent_surface(category, value)
            if surface in result:
                raise ValueError(f"ambiguous source attribute surface: {surface}")
            result[surface] = {"cat": category, "val": value}
    return result


def _parse_source_clue(
    clue_id: str,
    sentence: str,
    categories: dict[str, list[str]],
) -> dict[str, Any]:
    surfaces = _source_surface_map(categories)
    text = sentence.rstrip(".").casefold()

    def attribute(value: str) -> dict[str, str] | None:
        return surfaces.get(value.strip())

    unary = re.fullmatch(
        r"(.+) is (not )?in the (first|second|third|fourth|fifth|sixth) house", text
    )
    if unary is not None and (item := attribute(unary.group(1))) is not None:
        return {
            "id": clue_id,
            "type": "not_at" if unary.group(2) else "found_at",
            **item,
            "house": ORDINAL_VALUES[unary.group(3)],
        }
    for separator, clue_type in SOURCE_RELATIONS:
        if separator in text:
            left, right = text.split(separator, 1)
            a, b = attribute(left), attribute(right)
            if a is not None and b is not None:
                return {"id": clue_id, "type": clue_type, "a": a, "b": b}
            break
    between = re.fullmatch(
        r"(there is one house|there are two houses) between (.+) and (.+)", text
    )
    if between is not None:
        a, b = attribute(between.group(2)), attribute(between.group(3))
        if a is not None and b is not None:
            clue_type = "one_between" if between.group(1) == "there is one house" else "two_between"
            return {"id": clue_id, "type": clue_type, "a": a, "b": b}
    adjacent = re.fullmatch(r"(.+) and (.+) are next to each other", text)
    if adjacent is not None:
        a, b = attribute(adjacent.group(1)), attribute(adjacent.group(2))
        if a is not None and b is not None:
            return {"id": clue_id, "type": "side_by_side", "a": a, "b": b}
    for match in re.finditer(" is ", text):
        a, b = attribute(text[: match.start()]), attribute(text[match.end() :])
        if a is not None and b is not None:
            return {"id": clue_id, "type": "same_house", "a": a, "b": b}
    raise ValueError(f"source clue does not match independent audit grammar: {sentence}")


@dataclass(frozen=True)
class Finding:
    severity: str
    problem_id: str | None
    external_id: str | None
    field: str
    message: str
    source_file: str | None
    ingested_problem_path: str | None
    compiled_problem_path_or_row: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "problem_id": self.problem_id,
            "external_id": self.external_id,
            "field": self.field,
            "message": self.message,
            "source_file": self.source_file,
            "ingested_problem_path": self.ingested_problem_path,
            "compiled_problem_path_or_row": self.compiled_problem_path_or_row,
        }


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number} is not a JSON object")
        rows.append(value)
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as output:
        for row in rows:
            output.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _resolve_repo_path(repo_root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else repo_root / path


def _logical_key(values: dict[str, Any]) -> tuple[Any, Any, Any, Any]:
    return (DATASET_ID, values.get("split"), values.get("external_id"), values.get("grid"))


def _source_categories(raw: dict[str, Any]) -> tuple[int, dict[str, list[str]], list[str]]:
    size = raw.get("size")
    if not isinstance(size, str) or re.fullmatch(r"[1-9][0-9]*\*[1-9][0-9]*", size) is None:
        raise ValueError("source size is not NxM")
    houses, category_count = (int(value) for value in size.split("*"))
    solution = raw.get("solution")
    headers = solution.get("header") if isinstance(solution, dict) else None
    if not isinstance(headers, list) or headers[:1] != ["House"]:
        raise ValueError("source solution header is missing House")
    category_names = headers[1:]
    puzzle = raw.get("puzzle")
    if not isinstance(puzzle, str):
        raise ValueError("source puzzle text is missing")
    bullets = [line for line in puzzle.splitlines() if line.startswith(" - ")]
    if len(category_names) != category_count or len(bullets) != category_count:
        raise ValueError("source category count disagrees with size/header/declarations")
    categories: dict[str, list[str]] = {}
    for name, bullet in zip(category_names, bullets, strict=True):
        if not isinstance(name, str) or not name:
            raise ValueError("source category name is invalid")
        values = re.findall(r"`([^`]*)`", bullet)
        if len(values) != houses:
            raise ValueError(f"source category {name} has {len(values)} values, expected {houses}")
        categories[name] = values
    clues = [
        match.group(2)
        for line in puzzle.splitlines()
        if (match := re.fullmatch(r"([1-9][0-9]*)\. (.+)", line)) is not None
    ]
    return houses, categories, clues


def _clue_attributes(clue: dict[str, Any]) -> list[dict[str, Any]]:
    if clue.get("type") in {"found_at", "not_at"}:
        return [clue]
    return [value for value in (clue.get("a"), clue.get("b")) if isinstance(value, dict)]


def _category_map(compiled_categories: Any) -> dict[str, list[str]]:
    if not isinstance(compiled_categories, list):
        raise ValueError("compiled_categories is not an array")
    result: dict[str, list[str]] = {}
    for category in compiled_categories:
        if not isinstance(category, dict):
            raise ValueError("compiled category is not an object")
        name = category.get("name")
        values = category.get("values")
        if not isinstance(name, str) or not isinstance(values, list) or not all(
            isinstance(value, str) for value in values
        ):
            raise ValueError("compiled category name/values are malformed")
        if name in result:
            raise ValueError(f"duplicate compiled category: {name}")
        result[name] = values
    return result


def _index_rows(path: Path) -> dict[str, str]:
    rows: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"\| `(zl_[^`]+)` \|", line)
        if match is not None:
            rows[match.group(1)] = line
    return rows


class DatasetAuditor:
    def __init__(
        self,
        repo_root: Path,
        gate_dir: Path,
        output_dir: Path,
        command: str,
        expected_records: list[SourceRecord] | None = None,
    ) -> None:
        self.repo_root = repo_root.resolve()
        self.gate_dir = gate_dir.resolve()
        self.output_dir = output_dir.resolve()
        self.command = command
        self.findings: list[Finding] = []
        if expected_records is None:
            expected_records, _roots = load_official_source(self.repo_root)
        self.expected_records = expected_records
        self.expected_by_id = {record.problem_id: record for record in expected_records}
        self.expected_by_key = {record.key: record for record in expected_records}
        self.expected_by_location = {
            (record.source_file, record.source_row_index): record for record in expected_records
        }

    def add(
        self,
        severity: str,
        field: str,
        message: str,
        *,
        source: dict[str, Any] | None = None,
        problem_id: str | None = None,
        external_id: str | None = None,
        ingested_path: str | None = None,
        compiled_row: str | None = None,
    ) -> None:
        source = source or {}
        self.findings.append(
            Finding(
                severity=severity,
                problem_id=problem_id or source.get("problem_id"),
                external_id=external_id or source.get("external_id"),
                field=field,
                message=message,
                source_file=source.get("source_file"),
                ingested_problem_path=ingested_path or source.get("ingested_problem_path"),
                compiled_problem_path_or_row=compiled_row,
            )
        )

    def _load_gate_rows(self) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        manifest = _read_json(self.gate_dir / "manifest.json")
        source_rows = _read_jsonl(self.gate_dir / "source_manifest.jsonl")
        results = _read_jsonl(self.gate_dir / "results.jsonl")
        compiled = _read_jsonl(self.gate_dir / "compiled_problems.jsonl")
        return manifest, source_rows, results, compiled

    def _check_source_rows(self, source_rows: list[dict[str, Any]]) -> None:
        for row_number, row in enumerate(source_rows, start=1):
            source_file_value = row.get("source_file")
            if not isinstance(source_file_value, str):
                self.add("error", "source_row_missing", f"source row {row_number} has no source_file", source=row)
                continue
            source_path = _resolve_repo_path(self.repo_root, source_file_value)
            if not source_path.is_file():
                self.add("error", "source_row_missing", f"source file does not exist: {source_file_value}", source=row)
                continue
            if "eval/gates" in Path(source_file_value).parts:
                self.add(
                    "error",
                    "invented_problem_no_source",
                    "generated gate artifact was recorded as a source file",
                    source=row,
                )
            try:
                if source_path.suffix == ".parquet":
                    index = row.get("source_row_index")
                    if not isinstance(index, int):
                        raise ValueError(f"invalid source_row_index: {index!r}")
                    record = self.expected_by_location.get((source_file_value, index))
                    if record is None:
                        raise ValueError("source_file/source_row_index does not locate an eval row")
                    if row.get("source_record_id") != record.external_id:
                        raise ValueError("source_record_id does not match Parquet row id")
                    if row.get("source_sha256") != canonical_record_sha256(record.raw):
                        self.add("error", "source_hash_mismatch", "source record SHA-256 mismatch", source=row)
                    if row.get("source_file_sha256") != file_sha256(source_path):
                        self.add("error", "source_hash_mismatch", "source file SHA-256 mismatch", source=row)
                    if _logical_key(row) != record.key:
                        self.add("error", "source_row_missing", "source metadata does not match located Parquet row", source=row)
                else:
                    digest = file_sha256(source_path)
                    if row.get("source_sha256") != digest or row.get("source_file_sha256") != digest:
                        self.add("error", "source_hash_mismatch", "standalone source file SHA-256 mismatch", source=row)
                    raw = _read_json(source_path)
                    if source_path.name.endswith(".problem.json"):
                        raw_source = raw.get("source") if isinstance(raw, dict) else None
                        if not isinstance(raw_source, dict) or (
                            raw_source.get("external_id"), raw_source.get("split"), raw_source.get("grid")
                        ) != (row.get("external_id"), row.get("split"), row.get("grid")):
                            raise ValueError("converted fixture metadata does not match source manifest")
                    elif not isinstance(raw, dict) or raw.get("id") != row.get("source_record_id"):
                        raise ValueError("standalone raw source id does not match source_record_id")
            except Exception as exc:
                self.add("error", "source_row_missing", str(exc), source=row)

    def _check_duplicates(self, source_rows: list[dict[str, Any]]) -> None:
        ingested_by_key: dict[tuple[Any, Any, Any, Any], list[dict[str, Any]]] = {}
        for row in source_rows:
            if row.get("status") == "ingested":
                ingested_by_key.setdefault(_logical_key(row), []).append(row)
        for key, rows in ingested_by_key.items():
            if len(rows) > 1:
                for row in rows:
                    self.add(
                        "error",
                        "duplicate_logical_problem",
                        f"logical key {key!r} is ingested {len(rows)} times",
                        source=row,
                    )
        for row in source_rows:
            if row.get("status") == "skipped" and _logical_key(row) not in ingested_by_key:
                self.add(
                    "error",
                    "source_row_missing",
                    "skipped source duplicate has no canonical ingested logical problem",
                    source=row,
                )

    def _check_full_source_coverage(self, source_rows: list[dict[str, Any]]) -> None:
        ingested_keys = {
            _logical_key(row) for row in source_rows if row.get("status") == "ingested"
        }
        for key, record in self.expected_by_key.items():
            if key not in ingested_keys:
                self.add(
                    "error",
                    "missing_eval_problem",
                    "official eval source record is absent from ingestion",
                    problem_id=record.problem_id,
                    external_id=record.external_id,
                    source={"source_file": record.source_file},
                )
        for key in ingested_keys - self.expected_by_key.keys():
            row = next(row for row in source_rows if _logical_key(row) == key)
            self.add(
                "error",
                "invented_problem_no_source",
                "ingested logical problem is not in the authoritative eval source",
                source=row,
            )

    def _check_gate_manifest(
        self,
        manifest: dict[str, Any],
        source_rows: list[dict[str, Any]],
        result_rows: list[dict[str, Any]],
        compiled_rows: list[dict[str, Any]],
    ) -> None:
        expected = {
            "status": "pass",
            "total_source_records_seen": len(source_rows),
            "total_ingested": sum(row.get("status") == "ingested" for row in source_rows),
            "total_compiled": len(compiled_rows),
            "total_failed": 0,
            "total_skipped": sum(row.get("status") == "skipped" for row in source_rows),
        }
        for field, value in expected.items():
            if manifest.get(field) != value:
                self.add(
                    "error",
                    "artifact_unreadable",
                    f"Gate manifest {field}={manifest.get(field)!r}; expected {value!r}",
                )
        if manifest.get("failures") != []:
            self.add("error", "artifact_unreadable", "passing Gate manifest failures is not empty")
        if len(result_rows) != expected["total_ingested"]:
            self.add(
                "error",
                "compiled_row_missing",
                "results.jsonl row count does not equal total ingested problems",
            )

    def _source_match(
        self,
        source: dict[str, Any],
        problem: dict[str, Any],
        record: SourceRecord,
    ) -> tuple[int, int]:
        try:
            houses, categories, source_clues = _source_categories(record.raw)
        except Exception as exc:
            self.add("error", "source_row_missing", str(exc), source=source)
            return 0, 0
        expected_identity = {
            "problem_id": record.problem_id,
            "external_id": record.external_id,
            "split": record.split,
            "grid": record.grid,
        }
        actual_source = problem.get("source") if isinstance(problem.get("source"), dict) else {}
        actual_identity = {
            "problem_id": problem.get("id"),
            "external_id": actual_source.get("external_id"),
            "split": actual_source.get("split"),
            "grid": actual_source.get("grid"),
        }
        identity_fields = {
            "problem_id": "problem_id_mismatch",
            "external_id": "external_id_mismatch",
            "split": "split_mismatch",
            "grid": "grid_mismatch",
        }
        for field, expected in expected_identity.items():
            if actual_identity[field] != expected or source.get(field) != expected:
                self.add(
                    "error",
                    identity_fields[field],
                    f"expected {expected!r}, got source={source.get(field)!r}, raw={actual_identity[field]!r}",
                    source=source,
                )
        raw_size = problem.get("size")
        if not isinstance(raw_size, dict) or raw_size.get("houses") != houses:
            self.add("error", "grid_mismatch", f"raw house count does not match source: {houses}", source=source)
        if not isinstance(raw_size, dict) or raw_size.get("categories") != len(categories):
            self.add("error", "category_missing", "raw category count does not match source", source=source)
        raw_categories = problem.get("categories")
        if raw_categories != categories:
            self.add(
                "error",
                "category_value_mismatch",
                "raw category names/value arrays do not exactly match source declarations",
                source=source,
            )
        raw_clues = problem.get("clues")
        if not isinstance(raw_clues, list):
            self.add("error", "clue_count_mismatch", "raw clues is not an array", source=source)
            return len(categories), len(source_clues)
        if len(raw_clues) != len(source_clues):
            self.add(
                "error",
                "clue_count_mismatch",
                f"source has {len(source_clues)} clues; raw problem has {len(raw_clues)}",
                source=source,
            )
        clue_ids = [clue.get("id") for clue in raw_clues if isinstance(clue, dict)]
        if len(clue_ids) != len(set(clue_ids)):
            self.add("error", "clue_id_mismatch", "raw clue IDs are not unique", source=source)
        for index, (clue, source_text) in enumerate(zip(raw_clues, source_clues, strict=False), start=1):
            if not isinstance(clue, dict):
                self.add("error", "clue_type_mismatch", f"clue {index} is not an object", source=source)
                continue
            if clue.get("id") != f"c{index}":
                self.add(
                    "error",
                    "clue_id_mismatch",
                    f"source clue {index} maps to {clue.get('id')!r}, expected c{index}",
                    source=source,
                )
            for attribute in _clue_attributes(clue):
                category = attribute.get("cat")
                value = attribute.get("val")
                if category not in categories or value not in categories.get(category, []):
                    self.add(
                        "error",
                        "clue_operand_mismatch",
                        f"clue {index} references undeclared scoped value {category}.{value}",
                        source=source,
                    )
            try:
                expected_clue = _parse_source_clue(f"c{index}", source_text, categories)
            except Exception as exc:
                self.add(
                    "error",
                    "clue_operand_mismatch",
                    f"source clue {index}: {exc}",
                    source=source,
                )
                continue
            if clue != expected_clue:
                field = (
                    "clue_type_mismatch"
                    if clue.get("type") != expected_clue.get("type")
                    else "clue_operand_mismatch"
                )
                self.add(
                    "error",
                    field,
                    f"raw clue {index} does not equal independently parsed source clue",
                    source=source,
                )
        return len(categories), len(raw_clues)

    def _compiled_match(
        self,
        source: dict[str, Any],
        problem: dict[str, Any],
        result: dict[str, Any] | None,
        compiled: dict[str, Any] | None,
        result_row: str | None,
        compiled_row: str | None,
    ) -> tuple[int, int]:
        raw_categories = problem.get("categories")
        raw_clues = problem.get("clues")
        if result is None:
            self.add("error", "compiled_row_missing", "compile result row is missing", source=source)
        else:
            for field in ("problem_id", "external_id", "split", "grid"):
                if result.get(field) != source.get(field):
                    self.add(
                        "error",
                        f"{field}_mismatch",
                        f"compile result {field} does not match source manifest",
                        source=source,
                        compiled_row=result_row,
                    )
            if result.get("status") != "compiled" or result.get("protocol_kind") != "COMPILED":
                self.add(
                    "error",
                    "compiled_status_mismatch",
                    "compile result is not status=compiled/protocol_kind=COMPILED",
                    source=source,
                    compiled_row=result_row,
                )
            for field in ("error_code", "error_path", "error_message"):
                if result.get(field) is not None:
                    self.add(
                        "error",
                        "compiled_status_mismatch",
                        f"passing compile result has non-null {field}",
                        source=source,
                        compiled_row=result_row,
                    )
            if result.get("path") != source.get("ingested_problem_path"):
                self.add(
                    "error",
                    "compiled_row_missing",
                    "compile result path does not match ingested problem path",
                    source=source,
                    compiled_row=result_row,
                )
        if compiled is None:
            self.add("error", "compiled_row_missing", "compiled problem view row is missing", source=source)
            return 0, 0
        for field in ("problem_id", "external_id", "grid"):
            if compiled.get(field) != source.get(field):
                self.add(
                    "error",
                    f"{field}_mismatch",
                    f"compiled view {field} does not match source manifest",
                    source=source,
                    compiled_row=compiled_row,
                )
        if compiled.get("source_problem_path") != source.get("ingested_problem_path"):
            self.add(
                "error",
                "compiled_row_missing",
                "compiled view source_problem_path does not match ingested problem path",
                source=source,
                compiled_row=compiled_row,
            )
        if compiled.get("source_sha256") != source.get("source_sha256"):
            self.add(
                "error",
                "source_hash_mismatch",
                "compiled view source_sha256 does not match source manifest",
                source=source,
                compiled_row=compiled_row,
            )
        expected_houses = problem.get("size", {}).get("houses")
        if compiled.get("houses") != expected_houses:
            self.add("error", "compiled_category_mismatch", "compiled house count differs from raw", source=source, compiled_row=compiled_row)
        try:
            compiled_categories = _category_map(compiled.get("compiled_categories"))
        except Exception as exc:
            self.add("error", "compiled_category_mismatch", str(exc), source=source, compiled_row=compiled_row)
            compiled_categories = {}
        if compiled_categories != raw_categories or compiled.get("categories") != len(raw_categories or {}):
            self.add(
                "error",
                "compiled_category_mismatch",
                "compiled categories/value arrays do not exactly match raw problem",
                source=source,
                compiled_row=compiled_row,
            )
        compiled_clues = compiled.get("compiled_clues")
        if compiled_clues != raw_clues:
            self.add(
                "error",
                "compiled_clue_mismatch",
                "compiled clue array does not exactly match raw problem",
                source=source,
                compiled_row=compiled_row,
            )
        if isinstance(compiled_clues, list):
            ids = [clue.get("id") for clue in compiled_clues if isinstance(clue, dict)]
            if len(ids) != len(set(ids)) or set(ids) != {
                clue.get("id") for clue in raw_clues or [] if isinstance(clue, dict)
            }:
                self.add(
                    "error",
                    "compiled_clue_mismatch",
                    "compiled clue IDs are missing or duplicated",
                    source=source,
                    compiled_row=compiled_row,
                )
            for clue in compiled_clues:
                if not isinstance(clue, dict):
                    continue
                for attribute in _clue_attributes(clue):
                    category = attribute.get("cat")
                    value = attribute.get("val")
                    names = list(compiled_categories)
                    if category not in compiled_categories:
                        self.add(
                            "error",
                            "compiled_category_mismatch",
                            f"compiled clue category does not resolve: {category}",
                            source=source,
                            compiled_row=compiled_row,
                        )
                    elif value not in compiled_categories[category]:
                        self.add(
                            "error",
                            "compiled_clue_mismatch",
                            f"compiled clue value does not resolve: {category}.{value}",
                            source=source,
                            compiled_row=compiled_row,
                        )
                    else:
                        # Computing these positions proves the scoped names resolve uniquely.
                        names.index(category)
                        compiled_categories[category].index(value)
        return len(compiled_categories), len(compiled_clues) if isinstance(compiled_clues, list) else 0

    def _check_indexes(
        self,
        sources: list[dict[str, Any]],
        problems: dict[str, dict[str, Any]],
        compiled: dict[str, dict[str, Any]],
    ) -> None:
        expected_ids = {row["problem_id"] for row in sources}
        sources_by_id = {row["problem_id"]: row for row in sources}
        for filename, rows_for_examples in (
            ("raw_problem_index.md", problems),
            ("compiled_problem_index.md", compiled),
        ):
            path = self.gate_dir / filename
            if not path.is_file():
                self.add("error", "index_incomplete", f"missing human review index: {filename}")
                continue
            index = _index_rows(path)
            missing = expected_ids - index.keys()
            extra = index.keys() - expected_ids
            for problem_id in sorted(missing):
                self.add("error", "index_incomplete", f"{filename} is missing {problem_id}", problem_id=problem_id)
            for problem_id in sorted(extra):
                self.add("error", "index_incomplete", f"{filename} has unexpected {problem_id}", problem_id=problem_id)
            for problem_id in expected_ids & index.keys():
                row = rows_for_examples.get(problem_id, {})
                source = sources_by_id[problem_id]
                clues = row.get("clues") if filename.startswith("raw") else row.get("compiled_clues")
                if isinstance(clues, list):
                    expected_examples = [
                        f"{clue.get('id')}:{clue.get('type')}"
                        for clue in clues[:3]
                        if isinstance(clue, dict)
                    ]
                    if not all(example in index[problem_id] for example in expected_examples):
                        self.add(
                            "error",
                            "index_incomplete",
                            f"{filename} clue examples do not match artifact",
                            problem_id=problem_id,
                        )
                line = index[problem_id]
                if filename.startswith("raw"):
                    required_fragments = (
                        f"| {source['grid']} |",
                        f"`{source['source_file']}`",
                        f"`{source['ingested_problem_path']}`",
                    )
                else:
                    required_fragments = (
                        f"| {source['grid']} | {row.get('houses')} | "
                        f"{row.get('categories')} | {len(clues or [])} |",
                    )
                if not all(fragment in line for fragment in required_fragments):
                    self.add(
                        "error",
                        "index_incomplete",
                        f"{filename} metadata/counts do not match artifact",
                        problem_id=problem_id,
                    )

    def run(self) -> tuple[int, dict[str, Any]]:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        try:
            gate_manifest, source_rows, result_rows, compiled_rows = self._load_gate_rows()
        except Exception as exc:
            self.add("error", "artifact_unreadable", str(exc))
            source_rows, result_rows, compiled_rows = [], [], []
            gate_manifest = {}
        if gate_manifest.get("gate") != EXPECTED_GATE_NAME:
            self.add("error", "artifact_unreadable", "Gate manifest name is incorrect")
        self._check_gate_manifest(gate_manifest, source_rows, result_rows, compiled_rows)
        self._check_source_rows(source_rows)
        self._check_duplicates(source_rows)
        self._check_full_source_coverage(source_rows)

        ingested_sources = [row for row in source_rows if row.get("status") == "ingested"]
        results_by_id: dict[str, dict[str, Any]] = {}
        compiled_by_id: dict[str, dict[str, Any]] = {}
        for label, rows, destination in (
            ("compile result", result_rows, results_by_id),
            ("compiled view", compiled_rows, compiled_by_id),
        ):
            for row_number, row in enumerate(rows, start=1):
                problem_id = row.get("problem_id")
                if not isinstance(problem_id, str):
                    self.add("error", "compiled_row_missing", f"{label} row {row_number} lacks problem_id")
                elif problem_id in destination:
                    self.add("error", "duplicate_logical_problem", f"duplicate {label} row for {problem_id}", problem_id=problem_id)
                else:
                    destination[problem_id] = row

        referenced_paths: set[Path] = set()
        raw_problems: dict[str, dict[str, Any]] = {}
        audit_rows: list[dict[str, Any]] = []
        for source in ingested_sources:
            problem_id = source.get("problem_id")
            external_id = source.get("external_id")
            ingested_value = source.get("ingested_problem_path")
            problem: dict[str, Any] = {}
            if not isinstance(ingested_value, str):
                self.add("error", "invented_problem_no_source", "ingested problem path is missing", source=source)
            else:
                path = _resolve_repo_path(self.repo_root, ingested_value).resolve()
                referenced_paths.add(path)
                if not path.is_file():
                    self.add("error", "invented_problem_no_source", "ingested problem file is missing", source=source)
                else:
                    try:
                        loaded = _read_json(path)
                        if not isinstance(loaded, dict):
                            raise ValueError("ingested problem is not an object")
                        problem = loaded
                    except Exception as exc:
                        self.add("error", "invented_problem_no_source", str(exc), source=source)
            record = self.expected_by_id.get(str(problem_id))
            if record is None:
                self.add("error", "source_row_missing", "no authoritative source record for ingested problem", source=source)
                raw_category_count = raw_clue_count = 0
            else:
                raw_category_count, raw_clue_count = self._source_match(source, problem, record)
            result = results_by_id.get(str(problem_id))
            compiled = compiled_by_id.get(str(problem_id))
            compiled_category_count, compiled_clue_count = self._compiled_match(
                source,
                problem,
                result,
                compiled,
                f"results.jsonl:{result_rows.index(result) + 1}" if result in result_rows else None,
                f"compiled_problems.jsonl:{compiled_rows.index(compiled) + 1}" if compiled in compiled_rows else None,
            )
            if problem:
                raw_problems[str(problem_id)] = problem
            audit_rows.append(
                {
                    "problem_id": problem_id,
                    "external_id": external_id,
                    "grid": source.get("grid"),
                    "split": source.get("split"),
                    "source_file": source.get("source_file"),
                    "source_row_index": source.get("source_row_index"),
                    "source_sha256": source.get("source_sha256"),
                    "ingested_problem_path": ingested_value,
                    "compiled_status": result.get("status") if result else "missing",
                    "raw_category_count": raw_category_count,
                    "raw_clue_count": raw_clue_count,
                    "compiled_category_count": compiled_category_count,
                    "compiled_clue_count": compiled_clue_count,
                    "source_match_status": "pending",
                    "compiled_match_status": "pending",
                    "findings_count": 0,
                    "status": "pending",
                }
            )

        ingested_dir = self.gate_dir / "ingested_problems"
        if ingested_dir.is_dir():
            for path in ingested_dir.glob("*.problem.json"):
                if path.resolve() not in referenced_paths:
                    self.add(
                        "error",
                        "invented_problem_no_source",
                        "ingested problem file is not referenced by source manifest",
                        ingested_path=path.as_posix(),
                    )
        expected_problem_ids = {row.get("problem_id") for row in ingested_sources}
        for problem_id in results_by_id.keys() - expected_problem_ids:
            self.add("error", "invented_problem_no_source", "compile result has no ingested source", problem_id=problem_id)
        for problem_id in compiled_by_id.keys() - expected_problem_ids:
            self.add("error", "invented_problem_no_source", "compiled view has no ingested source", problem_id=problem_id)
        self._check_indexes(ingested_sources, raw_problems, compiled_by_id)

        for audit_row in audit_rows:
            related = [
                finding
                for finding in self.findings
                if finding.problem_id == audit_row["problem_id"]
            ]
            source_related = [
                finding
                for finding in related
                if finding.compiled_problem_path_or_row is None
                and finding.field != "index_incomplete"
            ]
            compiled_related = [
                finding
                for finding in related
                if finding.compiled_problem_path_or_row is not None
                or finding.field.startswith("compiled_")
            ]
            errors = sum(finding.severity == "error" for finding in related)
            warnings = sum(finding.severity == "warning" for finding in related)
            audit_row["source_match_status"] = (
                "fail" if any(item.severity == "error" for item in source_related) else "pass"
            )
            audit_row["compiled_match_status"] = (
                "fail" if any(item.severity == "error" for item in compiled_related) else "pass"
            )
            audit_row["findings_count"] = len(related)
            audit_row["status"] = "fail" if errors else ("warn" if warnings else "pass")

        total_errors = sum(finding.severity == "error" for finding in self.findings)
        total_warnings = sum(finding.severity == "warning" for finding in self.findings)
        manifest = {
            "audit": AUDIT_NAME,
            "status": "pass" if total_errors == 0 else "fail",
            "total_source_rows_checked": len(source_rows),
            "total_ingested_problems_checked": len(audit_rows),
            "total_compiled_rows_checked": len(compiled_rows),
            "total_findings": len(self.findings),
            "total_errors": total_errors,
            "total_warnings": total_warnings,
            "audited_gate_dir": (
                self.gate_dir.relative_to(self.repo_root).as_posix()
                if self.gate_dir.is_relative_to(self.repo_root)
                else self.gate_dir.as_posix()
            ),
        }
        _write_jsonl(self.output_dir / "problem_audit.jsonl", audit_rows)
        _write_jsonl(self.output_dir / "findings.jsonl", [finding.as_dict() for finding in self.findings])
        (self.output_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (self.output_dir / "summary.md").write_text(
            self._summary(manifest, audit_rows), encoding="utf-8"
        )
        return (0 if total_errors == 0 else 1), manifest

    def _summary(self, manifest: dict[str, Any], audit_rows: list[dict[str, Any]]) -> str:
        counts = Counter(finding.field for finding in self.findings)
        lines = [
            "# Stage 2 Gate A dataset audit",
            "",
            f"- Exact audit command run: `{self.command}`",
            f"- Status: **{manifest['status'].upper()}**",
            f"- Total source rows checked: {manifest['total_source_rows_checked']}",
            f"- Total ingested problems checked: {manifest['total_ingested_problems_checked']}",
            f"- Total compiled rows checked: {manifest['total_compiled_rows_checked']}",
            f"- Total errors: {manifest['total_errors']}",
            f"- Total warnings: {manifest['total_warnings']}",
            "- Safe to use for Gate B: " + ("yes" if manifest["status"] == "pass" else "no"),
            "",
            "## Top findings by category",
            "",
        ]
        if counts:
            lines.extend(f"- `{field}`: {count}" for field, count in counts.most_common(10))
        else:
            lines.append("- None. Every audited invariant passed.")
        lines.extend(["", "## Example source → raw → compiled mappings", ""])
        examples: list[dict[str, Any]] = []
        for grid in ("2x2", "4x4", "6x6"):
            example = next((row for row in audit_rows if row["grid"] == grid), None)
            if example is not None:
                examples.append(example)
        for row in examples:
            lines.append(
                f"- `{row['problem_id']}` ({row['grid']}): source `{row['source_file']}` row "
                f"{row['source_row_index']} → `{row['ingested_problem_path']}` → "
                f"compiled {row['compiled_category_count']} categories / {row['compiled_clue_count']} clues."
            )
        lines.extend(
            [
                "",
                "## Files for human review",
                "",
                "- `eval/gates/stage2_gate_a_compile_all/source_manifest.jsonl`",
                "- `eval/gates/stage2_gate_a_compile_all/compiled_problems.jsonl`",
                "- `eval/gates/stage2_gate_a_compile_all/raw_problem_index.md`",
                "- `eval/gates/stage2_gate_a_compile_all/compiled_problem_index.md`",
                "- `eval/gates/stage2_gate_a_compile_all_audit/problem_audit.jsonl`",
                "- `eval/gates/stage2_gate_a_compile_all_audit/findings.jsonl`",
                "",
            ]
        )
        return "\n".join(lines)


def run_audit(
    repo_root: Path,
    gate_dir: Path,
    output_dir: Path,
    command: str,
    expected_records: list[SourceRecord] | None = None,
) -> tuple[int, dict[str, Any]]:
    return DatasetAuditor(repo_root, gate_dir, output_dir, command, expected_records).run()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gate-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    gate_dir = args.gate_dir if args.gate_dir.is_absolute() else repo_root / args.gate_dir
    output_dir = args.output if args.output.is_absolute() else repo_root / args.output
    command = shlex.join(
        ["uv", "run", "python", "scripts/audit_stage2_gate_a_dataset.py", *sys.argv[1:]]
    )
    exit_code, manifest = run_audit(repo_root, gate_dir, output_dir, command)
    print(
        f"Stage 2 Gate A dataset audit: {manifest['status'].upper()} "
        f"({manifest['total_ingested_problems_checked']} problems, "
        f"{manifest['total_errors']} errors, {manifest['total_warnings']} warnings)"
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
