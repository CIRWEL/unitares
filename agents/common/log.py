"""Shared log rotation for UNITARES resident agents."""

from pathlib import Path


def trim_log(log_file: Path, max_lines: int) -> None:
    """Keep log file bounded to the last *max_lines* lines."""
    if not log_file.exists():
        return
    try:
        lines = log_file.read_text().splitlines()
    except OSError:
        return
    if len(lines) <= max_lines:
        return
    try:
        log_file.write_text("\n".join(lines[-max_lines:]) + "\n")
    except OSError:
        pass
