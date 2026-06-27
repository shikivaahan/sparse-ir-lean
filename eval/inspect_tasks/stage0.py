"""No-provider Inspect dry run for the Stage 0 dataset seam."""

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.solver import Generate, TaskState, solver

from sparseir_harness.dataset import load_zebra_subset


@solver
def dataset_probe():
    """Pass each loaded record through Inspect without calling a model."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        del generate
        return state

    return solve


@task
def stage0_dataset_dry_run() -> Task:
    manifest = load_zebra_subset()
    samples = [
        Sample(
            id=record.external_id,
            input=record.puzzle,
            metadata={
                "dataset": manifest.source_dataset,
                "external_id": record.external_id,
                "grid": record.grid,
                "split": record.split,
            },
        )
        for record in manifest.records
    ]
    return Task(dataset=samples, solver=dataset_probe(), scorer=None, model=None)
