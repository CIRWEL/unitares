"""
Optional REST API server.

Install with: pip install caldec[server]
Run with: caldec serve --port 8080

Provides:
    POST /record          - Record prediction
    POST /outcome         - Record outcome
    POST /calibrate       - Get calibrated confidence
    GET  /check           - Get calibration report
    GET  /drift           - Get drift report
"""

from __future__ import annotations
from pathlib import Path
from typing import Optional

__all__ = ["create_app", "serve"]


def create_app(data_dir: str = "data"):
    """Create FastAPI app with calibration endpoints."""
    try:
        from fastapi import FastAPI, HTTPException
        from pydantic import BaseModel
    except ImportError:
        raise ImportError("Install server dependencies: pip install caldec[server]")

    from .calibrator import Calibrator
    from .drift import DriftDetector

    app = FastAPI(
        title="caldec",
        description="Calibrated Decisions API",
        version="0.1.0",
    )

    data_path = Path(data_dir)
    cal = Calibrator(path=data_path / "calibration.json")
    drift = DriftDetector(path=data_path / "drift.json")

    class RecordRequest(BaseModel):
        confidence: float
        prediction: Optional[str] = None

    class OutcomeRequest(BaseModel):
        correct: bool
        prediction_id: Optional[str] = None
        weight: float = 1.0

    class RecordWithOutcomeRequest(BaseModel):
        confidence: float
        correct: bool
        weight: float = 1.0

    class CalibrateRequest(BaseModel):
        confidence: float

    @app.post("/record")
    def record(req: RecordRequest):
        """Record a prediction. Returns prediction_id for matching with /outcome."""
        pred_id = cal.record(req.confidence, req.prediction)
        return {"prediction_id": pred_id}

    @app.post("/outcome")
    def outcome(req: OutcomeRequest):
        """Record outcome for a prediction."""
        try:
            cal.outcome(req.correct, req.prediction_id, req.weight)
            drift.record(confidence=0.5, correct=req.correct)  # Also track in drift
            return {"status": "recorded"}
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.post("/record_with_outcome")
    def record_with_outcome(req: RecordWithOutcomeRequest):
        """Record prediction and outcome together."""
        cal.record_with_outcome(req.confidence, req.correct, req.weight)
        drift.record(req.confidence, req.correct)
        return {"status": "recorded"}

    @app.post("/calibrate")
    def calibrate(req: CalibrateRequest):
        """Get calibrated confidence."""
        adjusted, info = cal.calibrate(req.confidence)
        return {
            "raw": req.confidence,
            "calibrated": adjusted,
            "info": info,
        }

    @app.get("/check")
    def check():
        """Get calibration health report."""
        report = cal.check()
        return {
            "calibrated": report.calibrated,
            "total": report.total,
            "issues": report.issues,
            "bins": report.bins,
            "correction_factors": report.correction_factors,
            "summary": report.summary,
        }

    @app.get("/drift")
    def get_drift():
        """Get drift analysis report."""
        report = drift.check()
        return {
            "drifting": report.drifting,
            "drift_type": report.drift_type,
            "direction": report.direction,
            "severity": report.severity,
            "recommendation": report.recommendation,
            "details": report.details,
        }

    @app.get("/trend")
    def trend(window: int = 10):
        """Get accuracy trend for plotting."""
        return {"trend": drift.trend(window)}

    @app.post("/reset")
    def reset():
        """Reset all calibration data. Use with caution."""
        cal.reset()
        return {"status": "reset"}

    @app.get("/health")
    def health():
        """Health check."""
        return {"status": "ok", "version": "0.1.0"}

    return app


def serve(host: str = "0.0.0.0", port: int = 8080, data_dir: str = "data"):
    """Run the server."""
    try:
        import uvicorn
    except ImportError:
        raise ImportError("Install server dependencies: pip install caldec[server]")

    app = create_app(data_dir)
    uvicorn.run(app, host=host, port=port)
