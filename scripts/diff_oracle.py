#!/usr/bin/env python3
"""Development-only clingo availability probe for the Stage 0 oracle seam.

This stub deliberately does not encode ZebraLogic clues. The independent ASP
encoding and differential semantics belong to Stage 3.
"""

from __future__ import annotations

import argparse
import json

from sparseir_harness.oracle import probe


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--external-id")
    args = parser.parse_args()
    print(json.dumps(probe(args.external_id), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
