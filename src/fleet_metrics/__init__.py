"""Time-series store for catalog-defined fleet metrics.

- `catalog`: decorator-registered names that are allowed to be written.
- `storage`: async record/query helpers against `metrics.series`.

External writers (Chronicler resident agent, future scrapers) go through
catalog validation so a leaked bearer token cannot pollute history.
"""

from src.fleet_metrics.catalog import Metric, catalog, register, require
from src.fleet_metrics.storage import query, record

__all__ = ["Metric", "catalog", "register", "require", "query", "record"]
