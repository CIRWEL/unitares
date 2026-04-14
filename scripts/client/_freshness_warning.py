#!/usr/bin/env python3
"""Output a freshness warning if a skill's last_verified is stale. Used by session-start hook."""

import re
import sys
from datetime import datetime

content = sys.argv[1] if len(sys.argv) > 1 else ""

fm = re.search(r"^---\n(.*?)\n---", content, re.DOTALL)
if not fm:
    sys.exit(0)

fm_text = fm.group(1)
verified_m = re.search(r'last_verified:\s*["\'](\d{4}-\d{2}-\d{2})["\']', fm_text)
days_m = re.search(r"freshness_days:\s*(\d+)", fm_text)

if not verified_m or not days_m:
    sys.exit(0)

verified = datetime.strptime(verified_m.group(1), "%Y-%m-%d")
max_days = int(days_m.group(1))
age = (datetime.now() - verified).days

if age > max_days:
    print(
        f"WARNING: This skill was last verified {age} days ago (threshold: {max_days}). "
        f"Treat specific thresholds and behavioral claims as potentially outdated."
    )
