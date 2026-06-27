from sparseir_harness.oracle import probe


def test_clingo_is_callable_on_dataset_sample() -> None:
    result = probe("lgp-test-2x2-33")

    assert result["role"] == "reference_only"
    assert result["status"] == "callable"
    assert result["external_id"] == "lgp-test-2x2-33"
    assert result["sample_model"] == ["house(1)", "house(2)"]
