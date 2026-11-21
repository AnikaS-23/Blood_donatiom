"""
app/__init__.py
───────────────
Flask application factory – initialises all extensions and registers blueprints.
"""

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_bcrypt import Bcrypt
from flask_socketio import SocketIO
from flask_migrate import Migrate
from config import config_map

# ── Extension singletons (imported by models & other modules) ─────────────────
db           = SQLAlchemy()
login_manager = LoginManager()
bcrypt       = Bcrypt()
socketio     = SocketIO()
migrate      = Migrate()


def create_app(config_name: str = "default") -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="../static")
    app.config.from_object(config_map[config_name])

    # ── Initialise extensions ──────────────────────────────────────────────────
    db.init_app(app)
    bcrypt.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please log in to access this page."
    login_manager.login_message_category = "warning"

    socketio.init_app(
        app,
        async_mode=app.config["SOCKETIO_ASYNC_MODE"],
        cors_allowed_origins="*",
    )

    # ── Register blueprints ────────────────────────────────────────────────────
    from app.auth.routes    import auth_bp
    from app.hospital.routes import hospital_bp
    from app.bloodbank.routes import bloodbank_bp
    from app.admin.routes   import admin_bp
    from app.api.routes     import api_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(hospital_bp,  url_prefix="/hospital")
    app.register_blueprint(bloodbank_bp, url_prefix="/bloodbank")
    app.register_blueprint(admin_bp,     url_prefix="/admin")
    app.register_blueprint(api_bp,       url_prefix="/api")

    # ── Register SocketIO event handlers ──────────────────────────────────────
    from app.sockets import events  # noqa: F401

    # ── Shell context for flask shell ─────────────────────────────────────────
    @app.shell_context_processor
    def make_shell_context():
        from app.models import (User, Hospital, BloodBank, Inventory,
                                 InventoryTransaction, EmergencyRequest,
                                 EmergencyResponse, Notification,
                                 LowStockThreshold, DemandHistory)
        return dict(db=db, User=User, Hospital=Hospital, BloodBank=BloodBank,
                    Inventory=Inventory, EmergencyRequest=EmergencyRequest)

    return app
