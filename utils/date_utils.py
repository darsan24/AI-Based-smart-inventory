"""
Centralized date/time utility for Smart Inventory AI.

All date calculations across the application MUST use this module
to ensure consistent IST (Asia/Kolkata, UTC+05:30) handling.

Key concepts:
  - "current date"        → today in IST
  - "forecast target date"→ current_date + horizon_days
  - "generation date"     → when the forecast was computed (current date)
  - "last historical date"→ latest sales record date in the database
"""

from datetime import datetime, date, timedelta, timezone

# IST offset: UTC + 5 hours 30 minutes
IST = timezone(timedelta(hours=5, minutes=30))


def get_current_datetime_ist() -> datetime:
    """Returns the current datetime in IST (Asia/Kolkata)."""
    return datetime.now(IST)


def get_current_date_ist() -> date:
    """Returns today's date in IST (Asia/Kolkata)."""
    return get_current_datetime_ist().date()


def get_forecast_target_date(horizon_days: int, reference_date: date = None) -> date:
    """
    Calculates the forecast target date.

    Args:
        horizon_days: Number of days into the future (e.g. 7, 15, 30).
        reference_date: Optional override; defaults to today IST.

    Returns:
        The target date = reference_date + horizon_days.
    """
    if reference_date is None:
        reference_date = get_current_date_ist()
    return reference_date + timedelta(days=horizon_days)


def format_date_display(date_obj) -> str:
    """
    Formats a date for user-facing display: '21 Aug 2026'.

    Accepts date, datetime, or ISO string.
    """
    if date_obj is None:
        return "N/A"
    if isinstance(date_obj, str):
        try:
            date_obj = datetime.strptime(date_obj, "%Y-%m-%d").date()
        except ValueError:
            return date_obj
    if isinstance(date_obj, datetime):
        date_obj = date_obj.date()
    return date_obj.strftime("%d %b %Y")


def format_date_iso(date_obj) -> str:
    """Formats a date as ISO string: '2026-08-21'."""
    if date_obj is None:
        return ""
    if isinstance(date_obj, datetime):
        date_obj = date_obj.date()
    return date_obj.isoformat()


def get_latest_sale_date(db_session=None):
    """
    Returns the most recent sale_date in the sales table.

    This is the authoritative 'as-of' date for all date-windowed queries
    (dashboard trends, KPI windows, forecast reference dates, etc.).
    Falls back to today's IST date if no sales exist or if no session
    is provided.

    Args:
        db_session: SQLAlchemy session. If None, uses db.session from models.

    Returns:
        datetime.date of the latest sale, or today IST as fallback.
    """
    try:
        from models import Sale, db as app_db
        session = db_session or app_db.session
        from sqlalchemy import func
        latest = session.query(func.max(Sale.sale_date)).scalar()
        if latest is not None:
            if isinstance(latest, datetime):
                return latest.date()
            if isinstance(latest, str):
                return datetime.strptime(latest, '%Y-%m-%d').date()
            return latest
    except Exception:
        pass
    return get_current_date_ist()

