import sys, json
from typing import Any, Dict

from unitaires_core import (
    State, Theta, Weights,
    DEFAULT_STATE, DEFAULT_THETA, DEFAULT_WEIGHTS, DEFAULT_PARAMS,
    score_state, step_state, approximate_stability_check, suggest_theta_update,
)

current_state: State = DEFAULT_STATE
current_theta: Theta = DEFAULT_THETA

def handle_score_state(payload: Dict[str, Any]) -> Dict[str, Any]:
    global current_state
    ctx = payload["context_summary"]
    E = payload.get("E"); I = payload.get("I")
    S = payload.get("S"); V = payload.get("V")
    state = current_state
    if any(v is not None for v in (E, I, S, V)):
        state = State(
            E=E if E is not None else state.E,
            I=I if I is not None else state.I,
            S=S if S is not None else state.S,
            V=V if V is not None else state.V,
        )
    delta_eta = payload.get("delta_eta") or []
    wobj = payload.get("weights")
    weights = DEFAULT_WEIGHTS
    if wobj is not None:
        weights = Weights(
            wE=wobj.get("wE", DEFAULT_WEIGHTS.wE),
            wI=wobj.get("wI", DEFAULT_WEIGHTS.wI),
            wS=wobj.get("wS", DEFAULT_WEIGHTS.wS),
            wV=wobj.get("wV", DEFAULT_WEIGHTS.wV),
            wEta=wobj.get("wEta", DEFAULT_WEIGHTS.wEta),
        )
    result = score_state(ctx, state, delta_eta, weights)
    current_state = state
    return result

def handle_simulate_step(payload: Dict[str, Any]) -> Dict[str, Any]:
    global current_state, current_theta
    dt = float(payload["dt"])
    delta_eta = payload.get("delta_eta") or []
    noise_obj = payload.get("noise") or {}
    noise_S = float(noise_obj.get("S", 0.0))
    override = payload.get("override_state")
    state = current_state
    if override is not None:
        state = State(
            E=override.get("E", state.E),
            I=override.get("I", state.I),
            S=override.get("S", state.S),
            V=override.get("V", state.V),
        )
    new_state = step_state(state, current_theta, delta_eta, dt=dt,
                           noise_S=noise_S, params=DEFAULT_PARAMS)
    current_state = new_state
    return {
        "E": new_state.E,
        "I": new_state.I,
        "S": new_state.S,
        "V": new_state.V,
        "summary": (f"State advanced by dt={dt}. "
                    f"E={new_state.E:.3f}, I={new_state.I:.3f}, "
                    f"S={new_state.S:.3f}, V={new_state.V:.3f}."),
    }

def handle_check_stability(payload: Dict[str, Any]) -> Dict[str, Any]:
    samples = payload.get("samples")
    if samples is None:
        samples = 200
    return approximate_stability_check(current_theta, DEFAULT_PARAMS, int(samples))

def handle_suggest_theta_update(payload: Dict[str, Any]) -> Dict[str, Any]:
    global current_theta, current_state
    horizon = float(payload["horizon"])
    step = float(payload["step"])
    result = suggest_theta_update(current_theta, current_state, horizon, step,
                                  DEFAULT_PARAMS, DEFAULT_WEIGHTS)
    theta_dict = result["theta_new"]
    current_theta = Theta(C1=theta_dict["C1"], eta1=theta_dict["eta1"])
    return result

def handle_explain_drift(payload: Dict[str, Any]) -> Dict[str, Any]:
    delta_eta = payload.get("delta_eta") or []
    ctx = payload.get("context_summary", "")
    d_norm = sum(d*d for d in delta_eta)**0.5 if delta_eta else 0.0
    impact = {
        "E": "May change capacity allocation; large drift can distort resource focus.",
        "I": "Ethical drift tends to erode information integrity if repeated.",
        "S": "Increases uncertainty S via λ1(θ) ‖Δη‖²; higher drift means more disorder.",
        "V": "If drift separates E and I, void imbalance V grows and triggers corrections.",
    }
    overall = (f"For '{ctx}', the ethical drift norm is ‖Δη‖={d_norm:.3f}. "
               "Higher drift increases uncertainty, degrades integrity, and pushes the "
               "system away from balanced operation.")
    return {
        "delta_eta_norm": d_norm,
        "impact": impact,
        "overall": overall,
    }

HANDLERS = {
    "unitaires.score_state": handle_score_state,
    "unitaires.simulate_step": handle_simulate_step,
    "unitaires.check_stability": handle_check_stability,
    "unitaires.suggest_theta_update": handle_suggest_theta_update,
    "unitaires.explain_drift": handle_explain_drift,
}

def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            tool = req.get("tool")
            args = req.get("args", {})
            if tool not in HANDLERS:
                resp = {"ok": False, "error": f"Unknown tool: {tool}"}
            else:
                result = HANDLERS[tool](args)
                resp = {"ok": True, "result": result}
        except Exception as e:
            resp = {"ok": False, "error": str(e)}
        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()

if __name__ == "__main__":
    main()
