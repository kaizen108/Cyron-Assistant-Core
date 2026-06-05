"""Support hours check."""

from datetime import datetime
try:
    import pytz
    def _now_in_tz(tz_name: str) -> datetime:
        tz = pytz.timezone(tz_name)
        return datetime.now(tz)
except ImportError:
    from datetime import timezone
    def _now_in_tz(tz_name: str) -> datetime:
        return datetime.now(timezone.utc)


def is_support_open(panel: dict) -> tuple[bool, str]:
    """Returns (is_open, state). state: 'open' | 'closed'"""
    if not panel.get("support_hours_enabled"):
        return True, "open"

    tz_name = panel.get("support_hours_timezone", "UTC")
    try:
        now = _now_in_tz(tz_name)
    except Exception:
        now = datetime.utcnow()

    day = now.strftime("%A").lower()
    schedule = panel.get("support_hours_schedule") or {}
    day_config = schedule.get(day, {})

    if not day_config.get("enabled"):
        return False, "closed"

    open_time = day_config.get("open")
    close_time = day_config.get("close")
    if open_time and close_time:
        try:
            oh, om = map(int, open_time.split(":"))
            ch, cm = map(int, close_time.split(":"))
            current = now.hour * 60 + now.minute
            if oh * 60 + om <= current <= ch * 60 + cm:
                return True, "open"
        except Exception:
            pass

    return False, "closed"
