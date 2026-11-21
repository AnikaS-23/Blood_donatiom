"""
app/utils/alerts.py
────────────────────
Low-stock and expiry alert helpers.
Called after every inventory update and by the daily APScheduler job.
"""

from datetime import datetime, timedelta, timezone, date as date_type
from app import db, socketio
from app.models import Inventory, LowStockThreshold, Notification, BloodBank


def check_low_stock(blood_bank_id: int, blood_group: str, component: str, current_units: int):
    """
    Check if current_units is below the configured threshold for this
    (blood_bank, blood_group, component) combination.
    If so, create a notification and push a SocketIO event.
    Uses date-based dedup: only one alert per (bank, type, title) per day.
    """
    threshold_row = LowStockThreshold.query.filter_by(
        blood_bank_id=blood_bank_id,
        blood_group=blood_group,
        component=component,
        alert_active=True,
    ).first()

    threshold = threshold_row.threshold_units if threshold_row else 5

    if current_units <= threshold:
        level = "critical" if current_units == 0 else "low"
        title = f"{'🔴 Critical' if level == 'critical' else '🟡 Low'} Stock: {blood_group} {component}"
        message = (f"Only {current_units} unit(s) of {blood_group} {component} remaining. "
                   f"Threshold: {threshold}. Please restock.")

        # Date-based dedup: skip if already alerted today
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        existing = Notification.query.filter(
            Notification.recipient_type == "bloodbank",
            Notification.recipient_id == blood_bank_id,
            Notification.type == "Low Stock",
            Notification.title == title,
            Notification.created_at >= today_start,
        ).first()

        if not existing:
            notif = Notification(
                recipient_type="bloodbank",
                recipient_id=blood_bank_id,
                type="Low Stock",
                title=title,
                message=message,
            )
            db.session.add(notif)
            db.session.commit()

            socketio.emit("inventory_update", {
                "type"       : level,
                "blood_group": blood_group,
                "component"  : component,
                "units"      : current_units,
                "message"    : message,
            }, room=f"bloodbank_{blood_bank_id}")


def check_expiring_units(app):
    """
    APScheduler job: scan all inventory records for units expiring
    within EXPIRY_WARNING_DAYS (default 7). Run daily.
    """
    with app.app_context():
        warning_days = app.config.get("EXPIRY_WARNING_DAYS", 7)
        today = datetime.now(timezone.utc).date()
        cutoff = today + timedelta(days=warning_days)

        expiring = Inventory.query.filter(
            Inventory.expiry_date != None,
            Inventory.expiry_date <= cutoff,
            Inventory.expiry_date >= today,
            Inventory.units_available > 0,
        ).all()

        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

        for item in expiring:
            days_left = (item.expiry_date - today).days
            title = f"⚠️ Expiry Alert: {item.blood_group} {item.component}"
            message = (f"{item.units_available} unit(s) of {item.blood_group} {item.component} "
                       f"expire in {days_left} day(s) ({item.expiry_date}). Take action.")

            # Date-based dedup
            existing = Notification.query.filter(
                Notification.recipient_type == "bloodbank",
                Notification.recipient_id == item.blood_bank_id,
                Notification.type == "Expiry",
                Notification.title == title,
                Notification.created_at >= today_start,
            ).first()

            if not existing:
                notif = Notification(
                    recipient_type="bloodbank",
                    recipient_id=item.blood_bank_id,
                    type="Expiry",
                    title=title,
                    message=message,
                    reference_id=item.id,
                )
                db.session.add(notif)

        db.session.commit()


def generate_startup_alerts(app):
    """
    Run on app startup: scan ALL blood banks for current low-stock and
    expiry violations and generate initial notifications if none exist today.
    """
    with app.app_context():
        today = datetime.now(timezone.utc).date()
        cutoff = today + timedelta(days=7)
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

        # Expiry alerts
        expiring = Inventory.query.filter(
            Inventory.expiry_date != None,
            Inventory.expiry_date <= cutoff,
            Inventory.expiry_date >= today,
            Inventory.units_available > 0,
        ).all()

        for item in expiring:
            days_left = (item.expiry_date - today).days
            title = f"⚠️ Expiry Alert: {item.blood_group} {item.component}"
            message = (f"{item.units_available} unit(s) of {item.blood_group} {item.component} "
                       f"expire in {days_left} day(s) ({item.expiry_date}). Take action.")
            existing = Notification.query.filter(
                Notification.recipient_type == "bloodbank",
                Notification.recipient_id == item.blood_bank_id,
                Notification.type == "Expiry",
                Notification.title == title,
                Notification.created_at >= today_start,
            ).first()
            if not existing:
                db.session.add(Notification(
                    recipient_type="bloodbank",
                    recipient_id=item.blood_bank_id,
                    type="Expiry",
                    title=title,
                    message=message,
                    reference_id=item.id,
                ))

        # Low-stock alerts
        for bank in BloodBank.query.filter_by(is_active=True).all():
            thresholds = {
                (t.blood_group, t.component): t.threshold_units
                for t in LowStockThreshold.query.filter_by(
                    blood_bank_id=bank.id, alert_active=True).all()
            }
            for item in Inventory.query.filter_by(blood_bank_id=bank.id).all():
                threshold = thresholds.get((item.blood_group, item.component), 5)
                if item.units_available <= threshold:
                    level = "critical" if item.units_available == 0 else "low"
                    title = f"{'🔴 Critical' if level == 'critical' else '🟡 Low'} Stock: {item.blood_group} {item.component}"
                    message = (f"Only {item.units_available} unit(s) of {item.blood_group} "
                               f"{item.component} remaining. Threshold: {threshold}.")
                    existing = Notification.query.filter(
                        Notification.recipient_type == "bloodbank",
                        Notification.recipient_id == bank.id,
                        Notification.type == "Low Stock",
                        Notification.title == title,
                        Notification.created_at >= today_start,
                    ).first()
                    if not existing:
                        db.session.add(Notification(
                            recipient_type="bloodbank",
                            recipient_id=bank.id,
                            type="Low Stock",
                            title=title,
                            message=message,
                        ))

        db.session.commit()

