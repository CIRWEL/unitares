# Threshold Validation Plan

**Date:** 2025-11-25  
**Goal:** Empirically validate risk thresholds (especially 0.50 revise threshold)

---

## 🎯 Current Thresholds

- **RISK_APPROVE_THRESHOLD:** 0.30 (30%)
- **RISK_REVISE_THRESHOLD:** 0.50 (50%)
- **COHERENCE_CRITICAL_THRESHOLD:** 0.60 (60%)

**Status:** Not empirically validated - based on observed distribution

---

## 📊 Validation Methodology

### Step 1: Collect Ground Truth Data

**Data Collection:**
1. Label outputs as "good" vs "bad" (or "safe" vs "unsafe")
2. Record risk scores for all outputs
3. Record actual outcomes (did problems occur?)
4. Build dataset: `(risk_score, label, outcome)`

**Sources:**
- Historical governance decisions
- Manual labeling of sample outputs
- Incident reports (when risk was high but approved, or low but problems occurred)

### Step 2: Compute Metrics

**For each threshold candidate:**
- **True Positive Rate (TPR):** % of bad outputs correctly rejected
- **False Positive Rate (FPR):** % of good outputs incorrectly rejected
- **Precision:** % of rejected outputs that were actually bad
- **Recall:** % of bad outputs that were caught

### Step 3: ROC Curve Analysis

**Plot:**
- X-axis: False Positive Rate (FPR)
- Y-axis: True Positive Rate (TPR)
- Find optimal threshold: maximize TPR while minimizing FPR

**Optimal Threshold:**
- Maximize area under ROC curve (AUC)
- Or find threshold closest to (0, 1) on ROC curve
- Or use Youden's J statistic: J = TPR - FPR

### Step 4: Validate on Test Set

**Hold-out validation:**
- Train on 70% of data
- Validate on 30% of data
- Ensure thresholds generalize

---

## 🔧 Implementation Plan

### Phase 1: Data Collection Infrastructure

**Create:** `scripts/collect_validation_data.py`

```python
"""
Collect labeled data for threshold validation.

Usage:
    python scripts/collect_validation_data.py --label good --risk-score 0.25
    python scripts/collect_validation_data.py --label bad --risk-score 0.65
"""

import json
from pathlib import Path
from datetime import datetime

VALIDATION_DATA_FILE = Path("data/threshold_validation.jsonl")

def record_labeled_output(risk_score: float, label: str, outcome: str = None):
    """Record labeled output for validation"""
    entry = {
        "timestamp": datetime.now().isoformat(),
        "risk_score": risk_score,
        "label": label,  # "good" or "bad"
        "outcome": outcome,  # Optional: what actually happened
        "coherence": None,  # Can be filled in later
        "decision": None,  # Can be filled in later
    }
    
    with open(VALIDATION_DATA_FILE, 'a') as f:
        f.write(json.dumps(entry) + '\n')
```

### Phase 2: Analysis Script

**Create:** `scripts/analyze_thresholds.py`

```python
"""
Analyze threshold validation data and compute ROC curves.

Usage:
    python scripts/analyze_thresholds.py
"""

import json
import numpy as np
from pathlib import Path
from sklearn.metrics import roc_curve, auc, precision_recall_curve

def load_validation_data():
    """Load labeled validation data"""
    data_file = Path("data/threshold_validation.jsonl")
    if not data_file.exists():
        return [], []
    
    risk_scores = []
    labels = []
    
    with open(data_file, 'r') as f:
        for line in f:
            entry = json.loads(line)
            risk_scores.append(entry['risk_score'])
            labels.append(1 if entry['label'] == 'bad' else 0)
    
    return np.array(risk_scores), np.array(labels)

def compute_roc_curve(risk_scores, labels):
    """Compute ROC curve and find optimal threshold"""
    fpr, tpr, thresholds = roc_curve(labels, risk_scores)
    roc_auc = auc(fpr, tpr)
    
    # Find optimal threshold (Youden's J)
    j_scores = tpr - fpr
    optimal_idx = np.argmax(j_scores)
    optimal_threshold = thresholds[optimal_idx]
    
    return {
        'fpr': fpr,
        'tpr': tpr,
        'thresholds': thresholds,
        'auc': roc_auc,
        'optimal_threshold': optimal_threshold,
        'optimal_tpr': tpr[optimal_idx],
        'optimal_fpr': fpr[optimal_idx]
    }

def analyze_current_thresholds(risk_scores, labels):
    """Analyze performance of current thresholds"""
    thresholds = {
        'approve': 0.30,
        'revise': 0.50
    }
    
    results = {}
    for name, threshold in thresholds.items():
        predictions = (risk_scores >= threshold).astype(int)
        
        tp = np.sum((predictions == 1) & (labels == 1))
        fp = np.sum((predictions == 1) & (labels == 0))
        tn = np.sum((predictions == 0) & (labels == 0))
        fn = np.sum((predictions == 0) & (labels == 1))
        
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
        
        results[name] = {
            'threshold': threshold,
            'precision': precision,
            'recall': recall,
            'f1': f1,
            'tp': int(tp),
            'fp': int(fp),
            'tn': int(tn),
            'fn': int(fn)
        }
    
    return results

if __name__ == "__main__":
    risk_scores, labels = load_validation_data()
    
    if len(risk_scores) == 0:
        print("No validation data found. Run collect_validation_data.py first.")
    else:
        roc = compute_roc_curve(risk_scores, labels)
        current = analyze_current_thresholds(risk_scores, labels)
        
        print(f"ROC AUC: {roc['auc']:.3f}")
        print(f"Optimal threshold: {roc['optimal_threshold']:.3f}")
        print(f"\nCurrent thresholds:")
        for name, metrics in current.items():
            print(f"  {name} ({metrics['threshold']:.2f}):")
            print(f"    Precision: {metrics['precision']:.3f}")
            print(f"    Recall: {metrics['recall']:.3f}")
            print(f"    F1: {metrics['f1']:.3f}")
```

### Phase 3: Integration

**Add to governance flow:**
- Optionally record decisions with labels
- Build validation dataset over time
- Periodic threshold re-calibration

---

## 🎯 Separate Thresholds Proposal

### Current: Single Blended Risk Threshold

```python
risk = 0.7 * phi_risk + 0.3 * traditional_risk
if risk < 0.30: approve
if risk < 0.50: revise
else: reject
```

### Proposed: Separate Thresholds

```python
phi_risk = map_phi_to_risk(phi)
traditional_risk = estimate_traditional_risk(...)

# Separate decisions
if phi_risk < PHI_APPROVE_THRESHOLD and traditional_risk < TRADITIONAL_APPROVE_THRESHOLD:
    return APPROVE
elif phi_risk < PHI_REVISE_THRESHOLD and traditional_risk < TRADITIONAL_REVISE_THRESHOLD:
    return REVISE
else:
    return REJECT
```

**Benefits:**
- Clearer separation of ethical vs safety concerns
- Can tune each independently
- More interpretable decisions

**Drawbacks:**
- More complex decision logic
- Need to validate two thresholds
- May need conflict resolution

---

## 📋 Next Steps

1. **Immediate:** Document current blend (✅ Done)
2. **Short-term:** Create validation data collection script
3. **Medium-term:** Collect labeled data (100+ samples)
4. **Long-term:** Compute ROC curves and recalibrate thresholds
5. **Future:** Consider separate thresholds if validation shows benefit

---

**Status:** Infrastructure planned, ready to implement when validation data is available.

