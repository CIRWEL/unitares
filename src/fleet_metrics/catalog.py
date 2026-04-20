"""Catalog of allowed metric names.

Writing to `metrics.series` requires the name to be registered here.
A leaked bearer token therefore cannot inject arbitrary names into the
time-series — it can only write values for catalog-defined series.

New metrics are added by registering a `Metric` instance at import time.
Scrape implementations (in scrapers/ modules or the Chronicler agent) are
separate from catalog entries so the catalog stays a lightweight schema.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Metric:
    """A catalog entry for a time-series metric.

    The name is dotted (`tokei.unitares.src.code`) for readability; Postgres
    indexes it as plain TEXT, so there is no structural meaning to dots.

    `description` shows up in the catalog GET endpoint and dashboard so that
    a reader can tell what any series represents without digging for the
    scrape source.
    """

    name: str
    description: str
    unit: str = ""  # e.g. "lines", "seconds", "count", "" for dimensionless


catalog: dict[str, Metric] = {}


def register(metric: Metric) -> Metric:
    """Add a metric to the catalog. Idempotent on identical re-registration."""
    existing = catalog.get(metric.name)
    if existing is not None and existing != metric:
        raise ValueError(
            f"Metric {metric.name!r} is already registered with different "
            f"fields: existing={existing!r}, new={metric!r}"
        )
    catalog[metric.name] = metric
    return metric


def require(name: str) -> Metric:
    """Look up a metric by name; raise KeyError if the name is not registered."""
    try:
        return catalog[name]
    except KeyError as exc:
        raise KeyError(
            f"Metric {name!r} is not in the catalog. Register it in "
            f"src/fleet_metrics/catalog.py before writing."
        ) from exc


# ---------------------------------------------------------------------------
# Initial catalog
# ---------------------------------------------------------------------------
#
# Every metric defined here is one that answers a question the operator will
# actually ask monthly. New entries should meet the same bar — if nobody will
# read the resulting chart, it pollutes the surface area without paying rent.

register(Metric(
    name="tokei.unitares.src.code",
    description="Lines of code (excluding comments/blanks) in unitares/src/ — Python only.",
    unit="lines",
))

register(Metric(
    name="tests.unitares.count",
    description="Number of `test_*.py` files in unitares/tests/ — rough proxy for test-surface breadth.",
    unit="files",
))
