"""
run.py
──────
Entry point for the Blood Donor & Emergency Blood Availability Portal.
Run with:  python run.py
"""

import os
from app import create_app, socketio
from app.utils.scheduler import start_scheduler
from app.utils.alerts import generate_startup_alerts

app = create_app(os.environ.get("FLASK_ENV", "development"))

with app.app_context():
    start_scheduler(app)
    generate_startup_alerts(app)

if __name__ == "__main__":
    socketio.run(
        app,
        host="0.0.0.0",
        port=5000,
        debug=app.config["DEBUG"],
        use_reloader=False,
        allow_unsafe_werkzeug=True,
    )
