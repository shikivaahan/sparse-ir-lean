"""Regression test for stage6_h3_confidence._lenient_parse_confidence.

The previous implementation could misread "0.5%" as 0.5 (the bare-number
fallback swallowed the percent sign) and could fail to recover "99%" as 0.99
in some orderings. Percentages must be tried before bare numbers, and bare
numbers must reject any digits immediately followed by a percent sign.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src/sparseir_harness/stage6_h3_confidence.py"
spec = importlib.util.spec_from_file_location("stage6_h3_confidence", SCRIPT)
assert spec is not None and spec.loader is not None
mod = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = mod
spec.loader.exec_module(mod)
_parse = mod._lenient_parse_confidence


def test_bare_number_unchanged() -> None:
    assert _parse("0.75") == (0.75, "0.75")
    assert _parse("0") == (0.0, "0")
    assert _parse("1") == (1.0, "1")


def test_percentage_first() -> None:
    # The bug: "0.5%" was being read as 0.5, not 0.005.
    assert _parse("0.5%") == (0.005, "0.5%")
    # "99%" must be recoverable as 0.99.
    assert _parse("99%") == (0.99, "99%")


def test_percent_rejected_by_bare_fallback() -> None:
    # If a response wraps a percentage in prose, we still want the percentage.
    assert _parse("I am 0.5% sure") == (0.005, "I am 0.5% sure")
    assert _parse("answer: 99%") == (0.99, "answer: 99%")


def test_out_of_range_rejected() -> None:
    # 150% is not a valid confidence value; must not be returned.
    val, _ = _parse("150%")
    assert val is None


def test_no_number_returns_none() -> None:
    assert _parse("no digits here") == (None, "no digits here")
