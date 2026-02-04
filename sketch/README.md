# caldec

**Calibrated Decisions** - Confidence calibration for autonomous systems.

When your model says "90% confident", is it right 90% of the time? Usually not. This library tracks that gap and corrects it.

## Install

```bash
pip install calibrated-decisions

# With REST API server:
pip install calibrated-decisions[server]
```

## Quick Start

```python
from caldec import Calibrator

cal = Calibrator()

# Record predictions with outcomes
cal.record_with_outcome(confidence=0.9, correct=True)
cal.record_with_outcome(confidence=0.9, correct=False)
cal.record_with_outcome(confidence=0.9, correct=True)
# ... after many predictions ...

# Correct future predictions
raw = 0.9
adjusted, info = cal.calibrate(raw)
# If 90% confidence historically = 67% accuracy, adjusted ≈ 0.67

# Check calibration health
report = cal.check()
print(report.summary)  # "2 issues (100 samples)"
```

## Features

### 1. Calibrator
Tracks confidence bins, computes correction factors.

```python
from caldec import Calibrator

cal = Calibrator(path="calibration.json")  # Persist to file

# Two-step recording (when outcome comes later)
pred_id = cal.record(confidence=0.85)
# ... time passes ...
cal.outcome(correct=True, prediction_id=pred_id)

# Or record both at once
cal.record_with_outcome(confidence=0.85, correct=True)

# Get correction factors
report = cal.check()
# report.correction_factors = {"0.8-0.9": 0.78}  # Overconfident by 22%
```

### 2. DriftDetector
Monitors for degradation over time.

```python
from caldec import DriftDetector

drift = DriftDetector(window=100)

for prediction in stream:
    drift.record(prediction.confidence, prediction.was_correct)

report = drift.check()
if report.drifting:
    print(f"Alert: {report.drift_type}")
    print(f"Recommendation: {report.recommendation}")
```

### 3. Outcome Evaluation
Auto-evaluate from observable signals.

```python
from caldec import evaluate

# Evaluate from test/command/file results
correct = evaluate({
    "test": {"exit_code": 0},
    "command": {"success": True},
    "file": {"path": "/output.json", "exists": True},
})
# correct = True (all passed)
```

## REST API

```bash
caldec serve --port 8080
```

Endpoints:
- `POST /record` - Record prediction
- `POST /outcome` - Record outcome
- `POST /calibrate` - Get calibrated confidence
- `GET /check` - Calibration report
- `GET /drift` - Drift report

## CLI

```bash
caldec demo           # Run demo with simulated data
caldec check          # Check calibration status
caldec drift          # Check for drift
caldec serve          # Run REST API
```

## Use Cases

### Trading
```python
# Before position sizing, correct confidence
raw_conf = model.predict(data)
calibrated, _ = cal.calibrate(raw_conf)
position = base_size * kelly(calibrated)

# Alert on strategy degradation
if drift.check().severity > 0.15:
    alert("Strategy miscalibrated")
```

### ML in Production
```python
# Track model calibration over time
for pred, actual in zip(predictions, outcomes):
    cal.record_with_outcome(pred.probability, pred.label == actual)

if not cal.check().calibrated:
    trigger_retraining()
```

### Autonomous Agents
```python
# Evaluate from observable outcomes, no human labels
outcome = evaluate({
    "test": run_tests(),
    "command": execute_task(),
})
cal.record_with_outcome(agent.confidence, outcome)

# Use calibrated confidence for escalation
if cal.calibrate(agent.confidence)[0] < 0.5:
    escalate_to_human()
```

## Origin

Extracted from [UNITARES](https://github.com/yourname/unitares) governance framework. The original system had EISV dynamics, dialectic protocols, and embodied AI components. This is the part that actually matters for any decision-making system.

## License

MIT
