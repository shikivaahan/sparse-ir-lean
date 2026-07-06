# Public release notice

Copyright © 2026 Shiki Vaahan. All rights reserved.

Source code is published for research transparency and inspection. No licence for reuse, modification, or redistribution is granted at this time.

## Third-party material

This repository bundles three ZebraLogicBench records under
`src/sparseir_harness/data/zebra/`, used under the Creative Commons Attribution
4.0 International licence
(<https://creativecommons.org/licenses/by/4.0/>). Source records are unmodified
and provenance (external ID, split, grid, revision, path, SHA-256) is recorded
in the bundled dataset manifest. See
`src/sparseir_harness/data/zebra/ATTRIBUTION.md` for the record-level
attribution.

No other code in this repository is copied from third-party sources.

## Runtime dependencies

The Python and Lean builds rely on third-party packages and tools. Their
respective licences govern their own distribution:

- Lean 4.30.0 — Apache 2.0
- `clingo` 5.8.0 — MIT
- `inspect-ai` 0.3.241 — MIT
- `jsonschema` — MIT
- `openai` — Apache 2.0
- `pyarrow` — Apache 2.0
- `matplotlib` — MDT/BSD-3-Clause
- `pytest` — MIT
- `ruff` — MIT

Nothing in this notice grants any rights in those projects; their own
licences continue to govern them.

## Research data

The committed evaluation evidence under `eval/gates/` is part of the public
research artifact. The raw provider outputs preserved there are produced by
the model providers and included here for scientific transparency. They are
not subject to this notice's reuse restriction; they remain governed by the
providers' own terms.
