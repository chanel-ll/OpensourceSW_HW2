"""Pure scheduling rule; the current time is always passed in (no clock inside)."""
from datetime import timedelta


def update_due(last, now, interval_days=7):
    """Auto-update only when a previous update exists and is at least `interval_days` old."""
    return last is not None and now - last >= timedelta(days=interval_days)
