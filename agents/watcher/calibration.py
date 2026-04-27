"""Pure-function calibration math for Watcher self-calibration.

This module is I/O-free. It computes:

- ``jeffreys_lower_bound(successes, failures)`` — the 2.5% lower quantile
  of the Beta(0.5+s, 0.5+f) posterior. Used as the precision floor
  estimator. Compared to Wilson, it accepts fractional counts (we use
  decay-weighted observations) and has no degenerate behavior at small N.

- ``classify_file(path)`` — maps an absolute file path to one of six
  coarse classes ``{app, test, migration, generated, config, doc}``.
  Patterns calibrate per-(pattern × file_class) so a regex that's noisy
  on tests but precise on application code doesn't get globally demoted.

- ``decay_weight(detected_at, now, half_life_days)`` — exponential decay
  weight. Replaces a hard 90-day cutoff so rare patterns retain history
  and fast-moving ones weight recent reality.

- ``precision_by_pattern_and_class(findings, ...)`` — aggregates the
  above into the per-bucket precision dict consumed by floor_state.py.

Persistence and CLI wiring live elsewhere — keeping this file pure makes
the math trivially testable.
"""

from __future__ import annotations

import math
from pathlib import Path


# ---------------------------------------------------------------------------
# Jeffreys interval
# ---------------------------------------------------------------------------


def jeffreys_lower_bound(successes: float, failures: float) -> float:
    """2.5% lower quantile of the Beta(0.5+s, 0.5+f) posterior.

    Accepts non-integer counts (decay-weighted observations). Returns a
    value in [0, 1]. At s=f=0 the posterior is Beta(0.5, 0.5) and the
    lower bound is ~0.0015 — callers that distinguish "unmeasured" from
    "measured-as-zero" should gate on N separately.
    """
    if successes < 0 or failures < 0:
        raise ValueError(
            f"jeffreys_lower_bound: counts must be non-negative, "
            f"got successes={successes}, failures={failures}"
        )

    alpha = 0.5 + successes
    beta = 0.5 + failures
    return _beta_lower_quantile(alpha, beta, q=0.025)


def _beta_lower_quantile(alpha: float, beta: float, q: float) -> float:
    """Inverse-CDF of Beta(alpha, beta) at probability ``q``. Bisection on
    the regularized incomplete beta function. We use bisection rather than
    scipy to keep Watcher dependency-free.

    40 iterations of bisection over [0, 1] gives <1e-12 precision, well
    below the threshold-tuning resolution we care about (0.3).
    """
    lo, hi = 0.0, 1.0
    for _ in range(40):
        mid = (lo + hi) / 2.0
        if _beta_cdf(mid, alpha, beta) < q:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def _beta_cdf(x: float, alpha: float, beta: float) -> float:
    """Regularized incomplete beta function I_x(alpha, beta).

    Implementation: continued-fraction expansion (Numerical Recipes §6.4).
    Stable for the alpha/beta ranges Watcher produces (0.5 ≤ a ≤ ~10^4).
    """
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    log_bt = (
        math.lgamma(alpha + beta)
        - math.lgamma(alpha)
        - math.lgamma(beta)
        + alpha * math.log(x)
        + beta * math.log(1.0 - x)
    )
    bt = math.exp(log_bt)
    if x < (alpha + 1.0) / (alpha + beta + 2.0):
        return bt * _betacf(x, alpha, beta) / alpha
    return 1.0 - bt * _betacf(1.0 - x, beta, alpha) / beta


def _betacf(x: float, a: float, b: float, max_iter: int = 200, eps: float = 3e-7) -> float:
    """Continued-fraction evaluation for the incomplete beta. Lentz's
    method. ``max_iter=200`` is overkill for our parameter range; typical
    convergence is <30 iterations."""
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < 1e-30:
        d = 1e-30
    d = 1.0 / d
    h = d
    for m in range(1, max_iter + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < 1e-30:
            d = 1e-30
        c = 1.0 + aa / c
        if abs(c) < 1e-30:
            c = 1e-30
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < eps:
            return h
    return h


# ---------------------------------------------------------------------------
# File classifier
# ---------------------------------------------------------------------------


class FileClass:
    """Closed enum of file classes used as the second calibration axis.

    Strings (not IntEnum) so they round-trip through pattern_floor.json
    losslessly without requiring a converter. Ordering matters in
    ``classify_file`` — first match wins, with TEST checked before APP
    so test files inside src/ trees still classify as tests.
    """

    APP = "app"
    TEST = "test"
    MIGRATION = "migration"
    GENERATED = "generated"
    CONFIG = "config"
    DOC = "doc"


_TEST_FRAGMENTS = ("/tests/", "/test/")
_TEST_NAME_PREFIX = "test_"
_TEST_NAME_SUFFIX = "_test"

_MIGRATION_FRAGMENTS = ("/migrations/",)

_GENERATED_FRAGMENTS = ("/build/", "/dist/", "/__pycache__/", "/.venv/", "/node_modules/")
_GENERATED_SUFFIXES = (".pb.go", ".pb.py", ".min.js", ".pyc")

_CONFIG_FRAGMENTS = ("/.github/",)
_CONFIG_BASENAMES = frozenset({
    "pyproject.toml", "setup.cfg", "setup.py", "Makefile", "tox.ini",
    ".gitignore", ".dockerignore", "Dockerfile", "docker-compose.yml",
    "pre-commit-config.yaml", ".pre-commit-config.yaml",
})
_CONFIG_SUFFIXES = (".yml", ".yaml", ".toml", ".ini", ".cfg")

_DOC_SUFFIXES = (".md", ".rst", ".txt")
_DOC_BASENAMES = frozenset({"README", "CHANGELOG", "LICENSE", "NOTICE", "AUTHORS"})


def classify_file(path: str) -> str:
    """Map a file path to a FileClass.

    Order: test → migration → generated → doc → config → app. TEST wins
    over APP because tests/ trees often live inside src/ trees and the
    regex precision on test fixtures is qualitatively different from
    application code.
    """
    p = Path(path)
    name = p.name
    norm = "/" + str(p).strip("/")

    if any(frag in norm for frag in _TEST_FRAGMENTS):
        return FileClass.TEST
    if name.startswith(_TEST_NAME_PREFIX):
        return FileClass.TEST
    stem = p.stem
    if stem.endswith(_TEST_NAME_SUFFIX):
        return FileClass.TEST

    if any(frag in norm for frag in _MIGRATION_FRAGMENTS):
        return FileClass.MIGRATION

    if any(frag in norm for frag in _GENERATED_FRAGMENTS):
        return FileClass.GENERATED
    if any(name.endswith(suf) for suf in _GENERATED_SUFFIXES):
        return FileClass.GENERATED

    if name in _DOC_BASENAMES:
        return FileClass.DOC
    if any(name.endswith(suf) for suf in _DOC_SUFFIXES):
        return FileClass.DOC

    if any(frag in norm for frag in _CONFIG_FRAGMENTS):
        return FileClass.CONFIG
    if name in _CONFIG_BASENAMES:
        return FileClass.CONFIG
    if any(name.endswith(suf) for suf in _CONFIG_SUFFIXES):
        return FileClass.CONFIG

    return FileClass.APP
