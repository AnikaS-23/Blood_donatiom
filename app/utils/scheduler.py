"""
app/utils/scheduler.py
───────────────────────
APScheduler configuration – runs the daily expiry check job.
Call start_scheduler(app) from run.py or the app factory.
"""

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from app.utils.alerts import check_expiring_units

_scheduler = None


def start_scheduler(app):
    global _scheduler
    if _scheduler and _scheduler.running:
        return

    _scheduler = BackgroundScheduler()
    # Run daily at 06:00
    _scheduler.add_job(
        func=check_expiring_units,
        args=[app],
        trigger=CronTrigger(hour=6, minute=0),
        id="expiry_check",
        replace_existing=True,
    )
    _scheduler.start()
    app.logger.info("APScheduler started – expiry check runs daily at 06:00.")
