from src.eisv_state_json import normalize_agent_state_json


def test_safe_normalization_upgrades_legacy_state_json():
    normalized, changed = normalize_agent_state_json(
        {"E": 0.42, "phi": 0.33, "risk_score": 0.12, "verdict": "safe"},
        energy=0.42,
        integrity=0.81,
        entropy=0.12,
        void=-0.02,
        coherence=0.91,
        regime="CONVERGENCE",
    )

    assert changed is True
    assert normalized["primary_eisv"] == {"E": 0.42, "I": 0.81, "S": 0.12, "V": -0.02}
    assert normalized["primary_eisv_source"] == "legacy_flat"
    assert normalized["ode_eisv"] == {"E": 0.42, "I": 0.81, "S": 0.12, "V": -0.02}
    assert normalized["ode_diagnostics"] == {
        "phi": 0.33,
        "coherence": 0.91,
        "regime": "CONVERGENCE",
        "verdict": "safe",
        "risk_score": 0.12,
    }


def test_behavioral_payload_becomes_primary_source():
    normalized, changed = normalize_agent_state_json(
        {
            "E": 0.21,
            "behavioral_eisv": {"E": 0.71, "I": 0.82, "S": 0.11, "V": -0.03, "confidence": 1.0},
        },
        energy=0.21,
        integrity=0.4,
        entropy=0.5,
        void=0.6,
        coherence=0.7,
        regime="nominal",
    )

    assert changed is True
    assert normalized["E"] == 0.71
    assert normalized["primary_eisv"] == {"E": 0.71, "I": 0.82, "S": 0.11, "V": -0.03}
    assert normalized["primary_eisv_source"] == "behavioral"


def test_epoch2_inference_marks_early_rows_as_ode_fallback():
    normalized, changed = normalize_agent_state_json(
        {"E": 0.44},
        energy=0.44,
        integrity=0.55,
        entropy=0.22,
        void=0.03,
        coherence=0.88,
        regime="STABLE",
        source_strategy="epoch2_inference",
        row_index_within_identity=2,
    )

    assert changed is True
    assert normalized["primary_eisv_source"] == "ode_fallback"
    assert normalized["state_semantics_meta"] == {
        "source_inferred": True,
        "source_strategy": "epoch2_row_index",
        "row_index_within_identity": 2,
    }


def test_normalization_is_idempotent_for_explicit_state_json():
    payload = {
        "E": 0.61,
        "primary_eisv": {"E": 0.61, "I": 0.62, "S": 0.12, "V": -0.01},
        "primary_eisv_source": "behavioral",
        "behavioral_eisv": {"E": 0.61, "I": 0.62, "S": 0.12, "V": -0.01, "confidence": 1.0},
        "ode_eisv": {"E": 0.55, "I": 0.56, "S": 0.18, "V": 0.03},
        "ode_diagnostics": {"phi": 0.42, "coherence": 0.77, "regime": "CONVERGENCE", "verdict": "safe"},
    }

    normalized, changed = normalize_agent_state_json(
        payload,
        energy=0.61,
        integrity=0.62,
        entropy=0.12,
        void=-0.01,
        coherence=0.77,
        regime="CONVERGENCE",
    )

    assert changed is False
    assert normalized == payload
