"""Development-only clingo availability probe for the Stage 0 oracle seam."""

from __future__ import annotations

import clingo

from .dataset import load_zebra_subset


def probe(external_id: str | None = None) -> dict[str, object]:
    """Confirm clingo can ground and solve a trivial program for a real record.

    This deliberately does not encode ZebraLogic clues. The independent ASP
    encoding and differential semantics belong to Stage 3.
    """
    manifest = load_zebra_subset()
    candidates = [
        record for record in manifest.records if external_id is None or record.external_id == external_id
    ]
    if not candidates:
        raise ValueError(f"unknown external ID: {external_id}")
    record = candidates[0]

    control = clingo.Control(["--models=1"])
    control.add("base", [], f"house(1..{record.houses}).\n#show house/1.")
    control.ground([("base", [])])
    models: list[list[str]] = []

    def capture(model: clingo.Model) -> None:
        models.append(sorted(str(symbol) for symbol in model.symbols(shown=True)))

    result = control.solve(on_model=capture)
    if not result.satisfiable or not models:
        raise RuntimeError("clingo availability probe unexpectedly found no model")
    return {
        "oracle": "clingo",
        "role": "reference_only",
        "stage": 0,
        "external_id": record.external_id,
        "grid": record.grid,
        "status": "callable",
        "sample_model": models[0],
    }
