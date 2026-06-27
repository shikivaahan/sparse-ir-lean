import json
from pathlib import Path

from jsonschema import Draft202012Validator

from sparseir_harness.dataset import load_zebra_subset


ROOT = Path(__file__).resolve().parents[1]


def test_canonical_envelope_schema_accepts_dataset_metadata() -> None:
    schema = json.loads((ROOT / "schemas" / "problem-envelope.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    record = load_zebra_subset().records[0]
    envelope = {
        "schema_version": "0.2",
        "domain": "zebra",
        "id": f"zl_{record.external_id}",
        "source": {
            "dataset": "zebralogic",
            "split": record.split,
            "external_id": record.external_id,
            "grid": record.grid,
        },
        "expect": {"opaque": True},
    }

    Draft202012Validator(schema).validate(envelope)


def test_verifier_protocol_schema_is_version_stamped() -> None:
    schema = json.loads((ROOT / "schemas" / "verifier-protocol.schema.json").read_text())
    Draft202012Validator.check_schema(schema)
    assert schema["x-sparseir-interface"] == {
        "version": "0.1.0",
        "status": "frozen-stage-0",
        "transport": "single-request-json-stdin-single-response-json-stdout",
    }
