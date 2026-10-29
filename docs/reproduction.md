# Reproduction and artifact guide

[Home](../README.md) · [Architecture](architecture.md) · [Experiments](experiments.md) · [Verification](verification.md) · [Reproduction](reproduction.md) · [Roadmap](research-roadmap.md)

## Offline candidate walkthrough

From the repository root, build with `lake build`, then run this standard-library
Python example against a committed fixture. It checks one satisfying grid and one
complete but clue-violating grid; no dataset download or provider is involved.

```bash
python3 - <<'PY'
import json
import subprocess
from pathlib import Path

problem = json.loads(Path("tests/problems/lgp-test-2x2-33.problem.json").read_text())
candidate = {
    "schema_version": "0.2",
    "problem_id": problem["id"],
    "solution": {
        "Name": {"1": "Eric", "2": "Arnold"},
        "Pet": {"1": "cat", "2": "dog"},
    },
}
for pets in ({"1": "cat", "2": "dog"}, {"1": "dog", "2": "cat"}):
    candidate["solution"]["Pet"] = pets
    request = {
        "protocol_version": "0.1.0",
        "request_id": "offline-demo",
        "command": "check_candidate",
        "payload": {"problem": json.dumps(problem), "candidate": json.dumps(candidate)},
    }
    completed = subprocess.run(
        [".lake/build/bin/sparse-ir-lean"],
        input=json.dumps(request), text=True, capture_output=True, check=True,
    )
    print(json.dumps(json.loads(completed.stdout)["result"], indent=2))
PY
```

Expected results: `ACCEPT_SOLVED`, then `REJECT` with `clue_violation` for `c2`
(the dog cannot occupy house 1). The fixture's opaque `expect` field is not a
checker premise. See [verification](verification.md) for the guarantee's scope.

## Reproduce and inspect artifacts

Requirements: Lean 4 via the pinned toolchain, Python 3.11+, and `uv` or an equivalent Python environment manager. All research evidence links below are repository-local.

### Inspect the committed evidence

These artifacts contain the experiment configuration, per-example results, separated failure cases, aggregate metrics, and human-readable summaries. No provider credentials are needed to inspect them:

- [Capability ladder](../eval/gates/stage6_capability_ladder/summary.md): [metrics](../eval/gates/stage6_capability_ladder/metrics.json), [per-example results](../eval/gates/stage6_capability_ladder/results.jsonl), and [failures](../eval/gates/stage6_capability_ladder/failures.jsonl)
- [P(True) confidence comparison](../eval/gates/stage6_h3_confidence/summary.md): [metrics](../eval/gates/stage6_h3_confidence/metrics.json) and [per-example results](../eval/gates/stage6_h3_confidence/results.jsonl)
- [Reasoning ON/OFF comparison](../eval/gates/stage6_budget_sweep/summary.md): [metrics](../eval/gates/stage6_budget_sweep/metrics.json) and [per-example results](../eval/gates/stage6_budget_sweep/results.jsonl). Intermediate cap settings were not honored and should not be interpreted as a graded sweep.
- [Contamination perturbation smoke](../eval/gates/stage6_contamination/summary.md): [metrics](../eval/gates/stage6_contamination/metrics.json) and [per-example results](../eval/gates/stage6_contamination/results.jsonl)
- [Mode-0 pilot and artifact schema](../eval/gates/stage6_mode0_h2_h3/summary.md)
- [Stage 4 trace-parser gate and freeze record](../eval/gates/stage4_trace_parser/FREEZE.md): frozen `parse_trace` contract; 28 malformed fixtures covering all 26 error codes; JSON-Schema ↔ Lean-parser parity on 122 boundary cases with zero disagreements; 140 positive + 120 adversarial provider samples reparsed; 36-attempt stepwise trace-shape diagnostic with zero private-rule leakage in returned outputs.
- [Candidate-level differential checker test](../tests/test_stage3b_differential_candidates.py)

For example:

```bash
# Pretty-print aggregate capability-ladder metrics.
uv run python -m json.tool eval/gates/stage6_capability_ladder/metrics.json

# Pretty-print the first retained per-example result.
uv run python -c "import json, pathlib; p=pathlib.Path('eval/gates/stage6_capability_ladder/results.jsonl'); print(json.dumps(json.loads(p.open(encoding='utf-8').readline()), indent=2))"
```

### Run a fresh provider-backed smoke

After setting `OPENROUTER_API_KEY`, this runs a small balanced sample with reasoning ON, retains raw responses, checks every candidate in Lean, and writes results outside the committed gate directories:

```bash
uv run python scripts/run_stage6_cheap_smoke.py --output-dir .local/stage6-smoke --per-bin 1 --workers 1
```

Historical provider generations are not bit-reproducible: model endpoints and routing can change. The public tree commits configurations, parsed candidates, Lean verdicts, failure records, metrics, and manifests. Raw provider responses were retained before parsing during the runs but are not included in the public checkout; a fresh smoke stores its own raw responses under the selected output directory.

Full gate entrypoints live under `scripts/run_stage6_*.py`; they write to canonical gate directories, so use a disposable branch or checkout rather than overwriting the committed run.

### Re-run the checker validation offline

These focused gates exercise complete-candidate acceptance/rejection and compare Lean's candidate semantics against the independent clingo encoding without making provider calls:

```bash
lake build
uv sync --dev
uv run pytest tests/test_stage3a_candidate_checker.py tests/test_stage3b_differential_candidates.py
```

On a dataset-free public checkout, the Stage 3A module skips because the ingested
problem tree is absent. Stage 3B runs against committed fixtures and exercises
real Lean/clingo comparisons. The walkthrough above also needs no external data.

### Build and test the implementation

```bash
lake build
lake test
uv sync --dev
uv run pytest
```

The Python harness is orchestration, not part of the trusted checker.

### Public checkout validation vs full dataset-backed research gates

These are the **public-checkout validation** entrypoints, expected to pass with
explicit dataset-related skips on a clean clone. The
[CI workflow](../.github/workflows/ci.yml) also runs `uv run --frozen ruff check .`
and synchronizes locked dependencies with `uv sync --frozen --all-extras`.
CI must not receive provider credentials or depend on the external research
dataset; gate scripts remain separate from this public-checkout contract.

A small number of pytest modules genuinely depend on an external
research artifact. They call the shared skip helpers in
`tests/_dataset_prereq.py` at module load time, so on a public clone
they produce explicit skips with the exact reason:

* `requires external ZebraLogic source artifact: data/zebralogic/source.json`
* `requires ingested problem artifacts under eval/gates/stage2_gate_a_compile_all/ingested_problems/ ...`

Gate scripts under `scripts/` deliberately do NOT use the pytest skip
helper. If you invoke a gate script that requires the external ZebraLogic
source artifact without that artifact present, the script fails loudly
with `FileNotFoundError: data/zebralogic/source.json`. That is the
intended behavior: research-gate failures must remain loud.

### Running the full dataset-backed research gates

To exercise the dataset-backed gates (Stage 2 Gate A ingestion, Gate A
audit, Gate B mutation rejections, Gate B+ fuzz, Stage 3A candidate
checker, Stage 3C step kernel, Stage 6 Mode-0), the external ZebraLogic
source artifact must be placed at `data/zebralogic/source.json` (with
the parquet shard referenced by that metadata beside it). The
`eval/gates/stage2_gate_a_compile_all/ingested_problems/` tree is then
regenerated by:

```bash
PYTHONPATH=src uv run python scripts/stage2_gate_a_compile_all.py \
    --compiled-out eval/gates/stage2_gate_a_compile_all \
    --source-root data/zebralogic
```

Once the ingested problems exist on disk, the previously skipped tests
turn into real assertions automatically (the next `uv run pytest`
passes them). Gate commands that build on top of those ingested problems
(`scripts/audit_stage2_gate_a_dataset.py`, the Stage 2 Gate B scripts,
`scripts/run_stage6_*.py`, etc.) then run as designed. None of those
gate commands call OpenRouter when only the static / parsing /
gate-validation steps are run; the provider-backed smokes require
`OPENROUTER_API_KEY` and must be executed with disposable output
directories so they do not overwrite the committed gate artifacts.
