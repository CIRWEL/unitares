"""Normalization helpers for persisted agent-state EISV payloads."""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple


def _merge_payload(existing: Optional[Dict[str, Any]], defaults: Dict[str, Any]) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    for key, default_value in defaults.items():
        if isinstance(existing, dict) and existing.get(key) is not None:
            merged[key] = existing[key]
        elif default_value is not None:
            merged[key] = default_value
    return merged


def normalize_agent_state_json(
    state_json: Optional[Dict[str, Any]],
    *,
    energy: Optional[float],
    integrity: Optional[float],
    entropy: Optional[float],
    void: Optional[float],
    coherence: Optional[float],
    regime: Optional[str],
    source_strategy: str = "safe",
    row_index_within_identity: Optional[int] = None,
) -> Tuple[Dict[str, Any], bool]:
    """Upgrade persisted agent-state JSON to the explicit primary/behavioral/ODE schema.

    Returns ``(normalized_state_json, changed)``.

    ``source_strategy``:
    - ``safe``: never guesses; missing source becomes ``legacy_flat`` unless behavioral_eisv exists
    - ``epoch2_inference``: for epoch-2 historical rows, infer first two rows per identity as
      ``ode_fallback`` and later rows as ``behavioral``; records the inference in metadata
    """

    normalized: Dict[str, Any] = dict(state_json or {})
    original = dict(normalized)

    behavioral_eisv = normalized.get("behavioral_eisv") if isinstance(normalized.get("behavioral_eisv"), dict) else None
    primary_defaults = {
        "E": behavioral_eisv.get("E") if behavioral_eisv else (energy if energy is not None else normalized.get("E")),
        "I": behavioral_eisv.get("I") if behavioral_eisv else integrity,
        "S": behavioral_eisv.get("S") if behavioral_eisv else entropy,
        "V": behavioral_eisv.get("V") if behavioral_eisv else void,
    }
    primary_eisv = _merge_payload(
        normalized.get("primary_eisv") if isinstance(normalized.get("primary_eisv"), dict) else None,
        primary_defaults,
    )
    if primary_eisv:
        normalized["primary_eisv"] = primary_eisv
        if primary_eisv.get("E") is not None:
            normalized["E"] = primary_eisv["E"]

    ode_eisv = _merge_payload(
        (normalized.get("ode_eisv") if isinstance(normalized.get("ode_eisv"), dict) else None)
        or (normalized.get("ode") if isinstance(normalized.get("ode"), dict) else None),
        {
            "E": energy if energy is not None else normalized.get("E"),
            "I": integrity,
            "S": entropy,
            "V": void,
        },
    )
    if ode_eisv:
        normalized["ode_eisv"] = ode_eisv

    ode_diagnostics = _merge_payload(
        normalized.get("ode_diagnostics") if isinstance(normalized.get("ode_diagnostics"), dict) else None,
        {
            "phi": normalized.get("phi"),
            "coherence": coherence,
            "regime": regime,
            "verdict": normalized.get("verdict"),
            "risk_score": normalized.get("risk_score"),
        },
    )
    if ode_diagnostics:
        normalized["ode_diagnostics"] = ode_diagnostics

    if not normalized.get("primary_eisv_source"):
        if behavioral_eisv:
            normalized["primary_eisv_source"] = "behavioral"
        elif source_strategy == "epoch2_inference" and row_index_within_identity is not None:
            normalized["primary_eisv_source"] = "ode_fallback" if row_index_within_identity <= 2 else "behavioral"
            meta = dict(normalized.get("state_semantics_meta") or {})
            meta["source_inferred"] = True
            meta["source_strategy"] = "epoch2_row_index"
            meta["row_index_within_identity"] = row_index_within_identity
            normalized["state_semantics_meta"] = meta
        else:
            normalized["primary_eisv_source"] = "legacy_flat"

    return normalized, normalized != original
