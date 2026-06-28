"""Deterministic ingestion of the pinned ZebraLogicBench grid-mode templates.

The upstream rows contain natural-language puzzles generated from a fixed set of
surface templates.  This module maps that published template vocabulary to the
frozen Stage 1/2 Zebra clue algebra.  It does not generate puzzles or infer new
constraints: every emitted category, value, and clue comes from one source row.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DATASET_ID = "zebralogic"
UPSTREAM_DATASET = "allenai/ZebraLogicBench"
UPSTREAM_URL = "https://huggingface.co/datasets/allenai/ZebraLogicBench"
PINNED_REVISION = "a909ef550df0d218775ea6fc950368db34c98680"
PINNED_SHARD_SHA256 = "0886953f65988c2c14965192e8df0abf345dd84a31657bdb4f78fdf004907bc6"
SOURCE_METADATA = Path("data/zebralogic/source.json")


class IngestionError(ValueError):
    """A source row does not conform to the pinned ZebraLogic template vocabulary."""


@dataclass(frozen=True)
class SourceRecord:
    raw: dict[str, Any]
    problem_id: str
    external_id: str
    split: str
    grid: str
    source_file: str
    source_row_index: int | None
    source_record_id: str
    source_sha256: str
    source_file_sha256: str
    upstream_url: str | None

    @property
    def key(self) -> tuple[str, str, str, str]:
        return (DATASET_ID, self.split, self.external_id, self.grid)


def canonical_record_sha256(raw: dict[str, Any]) -> str:
    encoded = json.dumps(raw, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_official_source(repo_root: Path) -> tuple[list[SourceRecord], list[str]]:
    """Load all 1,000 records from the exact upstream Parquet shard pinned in-repo."""
    metadata_path = repo_root / SOURCE_METADATA
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    shard = metadata_path.parent / metadata["source_file"]
    actual_sha = file_sha256(shard)
    expected_sha = metadata["source_file_sha256"]
    if actual_sha != expected_sha or actual_sha != PINNED_SHARD_SHA256:
        raise IngestionError(f"source shard checksum mismatch: {shard}")
    if metadata.get("revision") != PINNED_REVISION:
        raise IngestionError("source metadata does not name the pinned upstream revision")

    import pyarrow.parquet as pq

    rows = pq.read_table(shard).to_pylist()
    expected_count = metadata.get("total_records")
    if len(rows) != expected_count:
        raise IngestionError(f"expected {expected_count} source rows, found {len(rows)}")

    source_file = shard.relative_to(repo_root).as_posix()
    records: list[SourceRecord] = []
    for index, raw in enumerate(rows):
        if not isinstance(raw, dict):
            raise IngestionError(f"source row {index} is not an object")
        external_id = _required_string(raw.get("id"), f"source row {index}.id")
        grid = _source_grid(_required_string(raw.get("size"), f"{external_id}.size"))
        records.append(
            SourceRecord(
                raw=raw,
                problem_id=f"zl_{external_id}",
                external_id=external_id,
                split="test",
                grid=grid,
                source_file=source_file,
                source_row_index=index,
                source_record_id=external_id,
                source_sha256=canonical_record_sha256(raw),
                source_file_sha256=actual_sha,
                upstream_url=metadata.get("upstream_url"),
            )
        )
    return records, [metadata_path.parent.relative_to(repo_root).as_posix()]


def _required_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise IngestionError(f"{field} must be a non-empty string")
    return value


def _source_grid(size: str) -> str:
    if re.fullmatch(r"[1-9][0-9]*\*[1-9][0-9]*", size) is None:
        raise IngestionError(f"invalid source grid size: {size!r}")
    return size.replace("*", "x")


def _template_map() -> dict[str, dict[str, str]]:
    templates: dict[str, dict[str, str]] = {
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
    templates["BookGenre"] = {
        value: f"the person who loves {value} books"
        for value in (
            "biography",
            "fantasy",
            "historical fiction",
            "mystery",
            "romance",
            "science fiction",
        )
    }
    templates["Occupation"] = {
        value: f"the person who is {'an' if value in {'artist', 'engineer'} else 'a'} {value}"
        for value in ("artist", "doctor", "engineer", "lawyer", "nurse", "teacher")
    }
    templates["Height"] = {
        value: (
            "the person who has an average height"
            if value == "average"
            else f"the person who is {value}"
        )
        for value in ("average", "short", "super tall", "tall", "very short", "very tall")
    }
    templates["HairColor"] = {
        value: f"the person who has {value} hair"
        for value in ("auburn", "black", "blonde", "brown", "gray", "red")
    }
    templates["MusicGenre"] = {
        value: f"the person who loves {value.replace('hip hop', 'hip-hop')} music"
        for value in ("classical", "country", "hip hop", "jazz", "pop", "rock")
    }
    templates["Mother"] = {
        value: f"the person whose mother's name is {value.lower()}"
        for value in ("Aniya", "Holly", "Janelle", "Kailyn", "Penny", "Sarah")
    }
    templates["PhoneModel"] = {
        value: f"the person who uses {'an' if value == 'iphone 13' else 'a'} {value}"
        for value in (
            "google pixel 6",
            "huawei p50",
            "iphone 13",
            "oneplus 9",
            "samsung galaxy s21",
            "xiaomi mi 11",
        )
    }
    templates["FavoriteSport"] = {
        value: f"the person who loves {value}"
        for value in ("baseball", "basketball", "soccer", "swimming", "tennis", "volleyball")
    }
    templates["CarModel"] = {
        value: f"the person who owns a {value.replace('ford f150', 'ford f-150')}"
        for value in (
            "bmw 3 series",
            "chevrolet silverado",
            "ford f150",
            "honda civic",
            "tesla model 3",
            "toyota camry",
        )
    }
    templates["Children"] = {
        value: (
            f"the person who is the mother of {value.lower()}"
            if value == "Timothy"
            else f"the person's child is named {value.lower()}"
        )
        for value in ("Alice", "Bella", "Fred", "Meredith", "Samantha", "Timothy")
    }
    return templates


ATTRIBUTE_TEMPLATES = _template_map()
ORDINAL_HOUSES = {
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
    "sixth": 6,
}
RELATION_SEPARATORS = (
    (" is directly left of ", "direct_left"),
    (" is directly right of ", "direct_right"),
    (" is somewhere to the left of ", "left_of"),
    (" is somewhere to the right of ", "right_of"),
)


def _parse_categories(raw: dict[str, Any]) -> tuple[int, dict[str, list[str]]]:
    puzzle = _required_string(raw.get("puzzle"), "puzzle")
    headers = raw.get("solution", {}).get("header")
    if not isinstance(headers, list) or headers[:1] != ["House"]:
        raise IngestionError("source solution header must start with House")
    category_names = headers[1:]
    if not all(isinstance(name, str) and name for name in category_names):
        raise IngestionError("source category headers must be non-empty strings")
    bullets = [line for line in puzzle.splitlines() if line.startswith(" - ")]
    if len(bullets) != len(category_names):
        raise IngestionError("source category headers and declarations disagree")
    categories: dict[str, list[str]] = {}
    for name, bullet in zip(category_names, bullets, strict=True):
        values = re.findall(r"`([^`]*)`", bullet)
        if not values:
            raise IngestionError(f"category {name!r} has no declared values")
        categories[name] = values
    houses_text, category_count_text = _required_string(raw.get("size"), "size").split("*")
    houses = int(houses_text)
    if int(category_count_text) != len(categories):
        raise IngestionError("source size category count does not match declarations")
    if any(len(values) != houses for values in categories.values()):
        raise IngestionError("source category value count does not match house count")
    return houses, categories


def _attribute_surfaces(categories: dict[str, list[str]]) -> dict[str, dict[str, str]]:
    surfaces = {value.lower(): {"cat": "Name", "val": value} for value in categories["Name"]}
    for category, values in categories.items():
        if category == "Name":
            continue
        if category not in ATTRIBUTE_TEMPLATES:
            raise IngestionError(f"unsupported ZebraLogic category template: {category}")
        for value in values:
            try:
                surface = ATTRIBUTE_TEMPLATES[category][value]
            except KeyError as exc:
                raise IngestionError(
                    f"unsupported ZebraLogic value template: {category}.{value}"
                ) from exc
            if surface in surfaces:
                raise IngestionError(f"ambiguous attribute surface template: {surface}")
            surfaces[surface] = {"cat": category, "val": value}
    return surfaces


def _parse_attribute(text: str, surfaces: dict[str, dict[str, str]]) -> dict[str, str] | None:
    return surfaces.get(text.strip().lower())


def _binary_clue(
    clue_id: str,
    clue_type: str,
    a_text: str,
    b_text: str,
    surfaces: dict[str, dict[str, str]],
) -> dict[str, Any] | None:
    a = _parse_attribute(a_text, surfaces)
    b = _parse_attribute(b_text, surfaces)
    if a is None or b is None:
        return None
    return {"id": clue_id, "type": clue_type, "a": a, "b": b}


def _parse_clue(clue_id: str, sentence: str, surfaces: dict[str, dict[str, str]]) -> dict[str, Any]:
    text = sentence.rstrip(".").lower()
    ordinals = "|".join(ORDINAL_HOUSES)
    unary = re.fullmatch(rf"(.+) is (not )?in the ({ordinals}) house", text)
    if unary is not None:
        attribute = _parse_attribute(unary.group(1), surfaces)
        if attribute is not None:
            return {
                "id": clue_id,
                "type": "not_at" if unary.group(2) else "found_at",
                **attribute,
                "house": ORDINAL_HOUSES[unary.group(3)],
            }

    for separator, clue_type in RELATION_SEPARATORS:
        if separator in text:
            a_text, b_text = text.split(separator, 1)
            parsed = _binary_clue(clue_id, clue_type, a_text, b_text, surfaces)
            if parsed is not None:
                return parsed
            break

    between = re.fullmatch(
        r"(there is one house|there are two houses) between (.+) and (.+)", text
    )
    if between is not None:
        clue_type = "one_between" if between.group(1) == "there is one house" else "two_between"
        parsed = _binary_clue(clue_id, clue_type, between.group(2), between.group(3), surfaces)
        if parsed is not None:
            return parsed

    adjacent = re.fullmatch(r"(.+) and (.+) are next to each other", text)
    if adjacent is not None:
        parsed = _binary_clue(
            clue_id, "side_by_side", adjacent.group(1), adjacent.group(2), surfaces
        )
        if parsed is not None:
            return parsed

    for boundary in (match.start() for match in re.finditer(" is ", text)):
        parsed = _binary_clue(
            clue_id, "same_house", text[:boundary], text[boundary + 4 :], surfaces
        )
        if parsed is not None:
            return parsed
    raise IngestionError(f"unsupported ZebraLogic clue template: {sentence}")


def convert_source_record(record: SourceRecord) -> dict[str, Any]:
    houses, categories = _parse_categories(record.raw)
    surfaces = _attribute_surfaces(categories)
    clue_lines = [
        line
        for line in _required_string(record.raw.get("puzzle"), "puzzle").splitlines()
        if re.match(r"^[1-9][0-9]*\. ", line)
    ]
    clues: list[dict[str, Any]] = []
    for expected_index, line in enumerate(clue_lines, start=1):
        match = re.fullmatch(r"([1-9][0-9]*)\. (.+)", line)
        if match is None or int(match.group(1)) != expected_index:
            raise IngestionError(f"non-sequential clue numbering in {record.external_id}")
        clues.append(_parse_clue(f"c{expected_index}", match.group(2), surfaces))
    if not clues:
        raise IngestionError(f"source record has no clues: {record.external_id}")
    return {
        "schema_version": "0.2",
        "domain": "zebra",
        "id": record.problem_id,
        "source": {
            "dataset": DATASET_ID,
            "split": record.split,
            "external_id": record.external_id,
            "grid": record.grid,
        },
        "size": {"houses": houses, "categories": len(categories)},
        "categories": categories,
        "clues": clues,
        "expect": {"source_solution": record.raw.get("solution")},
    }
