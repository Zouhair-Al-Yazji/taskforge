import os
import sys
from datetime import datetime, timezone

STATUS_CONFIG = {
    "PENDING": {"symbol": "◌", "color": "\033[33m"},
    "PROCESSING": {"symbol": "⚙ ", "color": "\033[36m"},
    "COMPLETED": {"symbol": "✓ ", "color": "\033[32m"},
    "FAILED": {"symbol": "✕ ", "color": "\033[31m"},
}
COLOR_RESET = "\033[0m"
STATUS_COLUMN_WIDTH = 14


def color_enabled() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    return sys.stdout.isatty()


def format_date(created_at_str: str) -> str:
    if not created_at_str:
        return "—"

    try:
        created_at_str = created_at_str.replace(" ", "T", 1)
        created_at = datetime.fromisoformat(created_at_str).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return str(created_at_str)

    now_utc = datetime.now(timezone.utc)
    seconds = int((now_utc - created_at).total_seconds())
    if seconds < 0:
        return "just now"
    elif seconds < 60:
        return f"{seconds}s ago"
    elif seconds < 3600:
        return f"{seconds // 60}m ago"
    elif seconds < 86400:
        return f"{seconds // 3600}h ago"
    else:
        return f"{seconds // 86400}d ago"


def format_status(raw_status: str, use_color: bool = True) -> str:
    config = STATUS_CONFIG.get(raw_status, {"symbol": "• ", "color": ""})
    combined = f"{config['symbol']} {raw_status}"
    padded = f"{combined:<{STATUS_COLUMN_WIDTH}}"

    if use_color and config["color"]:
        return f"{config['color']}{padded}{COLOR_RESET}"
    return padded
