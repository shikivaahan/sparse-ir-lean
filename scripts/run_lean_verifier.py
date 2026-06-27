#!/usr/bin/env python3
"""Untrusted transport wrapper for the Lean verifier subprocess."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


def invoke(request: dict[str, Any], executable: Path | None = None) -> dict[str, Any]:
    if executable:
        command = [str(executable)]
    else:
        lake = shutil.which("lake")
        elan_lake = Path.home() / ".elan" / "bin" / "lake"
        if lake is None and elan_lake.is_file():
            lake = str(elan_lake)
        if lake is None:
            raise RuntimeError("lake was not found on PATH or under ~/.elan/bin")
        command = [lake, "exe", "sparse-ir-lean"]
    completed = subprocess.run(
        command,
        input=json.dumps(request),
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"Lean verifier exited with {completed.returncode}: {completed.stderr.strip()}"
        )
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Lean verifier returned invalid JSON") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--executable", type=Path, help="prebuilt verifier executable (defaults to lake exe)"
    )
    parser.add_argument(
        "--request",
        default='{"protocol_version":"0.1.0","request_id":"cli","command":"info"}',
        help="JSON request object",
    )
    args = parser.parse_args()
    request = json.loads(args.request)
    if not isinstance(request, dict):
        parser.error("--request must decode to a JSON object")
    json.dump(invoke(request, args.executable), sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
