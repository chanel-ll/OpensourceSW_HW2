"""Rule 7: auto-update only when the last update is at least 7 days old; never without a record. `now` is an argument."""
from datetime import datetime, timedelta

from app.schedule import update_due

NOW = datetime(2026, 11, 27, 12, 0)


def test_no_record_means_no_auto_update():
    assert update_due(None, NOW) is False


def test_exactly_seven_days_is_due():
    assert update_due(NOW - timedelta(days=7), NOW) is True


def test_just_under_seven_days_is_not_due():
    assert update_due(NOW - timedelta(days=7) + timedelta(seconds=1), NOW) is False


def test_interval_comes_from_settings():
    assert update_due(NOW - timedelta(days=3), NOW, interval_days=3) is True


def test_clock_in_the_past_is_not_due():
    assert update_due(NOW + timedelta(hours=1), NOW) is False
