"""
app/models.py
─────────────
All SQLAlchemy models for the Blood Donor & Emergency Blood Availability Portal.
"""

from datetime import datetime, timezone
from app import db, login_manager
from flask_login import UserMixin
from flask_bcrypt import generate_password_hash, check_password_hash


# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

BLOOD_GROUPS = ["A+", "A-", "B+", "B-", "O+", "O-", "AB+", "AB-"]

BLOOD_COMPONENTS = [
    "Whole Blood",
    "Packed RBC",
    "Fresh Frozen Plasma",
    "Platelets",
    "Cryoprecipitate",
]

URGENCY_LEVELS = ["Critical", "High", "Medium"]

REQUEST_STATUSES = ["Pending", "Matched", "Fulfilled", "Cancelled"]

RESPONSE_STATUSES = ["Available", "Partial", "Unavailable"]

TRANSACTION_TYPES = ["Donation", "Issue", "Discard", "Transfer In", "Transfer Out"]

NOTIFICATION_TYPES = ["Emergency", "Low Stock", "Expiry", "System", "Response"]

USER_ROLES = ["hospital", "bloodbank", "admin"]


# ─────────────────────────────────────────────────────────────────────────────
# User
# ─────────────────────────────────────────────────────────────────────────────

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


class User(db.Model, UserMixin):
    __tablename__ = "users"

    id            = db.Column(db.Integer, primary_key=True)
    username      = db.Column(db.String(80), unique=True, nullable=False)
    email         = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    role          = db.Column(db.String(20), nullable=False)   # hospital | bloodbank | admin
    entity_id     = db.Column(db.Integer, nullable=True)       # FK to hospital or blood_bank
    is_active     = db.Column(db.Boolean, default=True)
    created_at    = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def set_password(self, password):
        self.password_hash = generate_password_hash(password).decode("utf-8")

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f"<User {self.username} [{self.role}]>"


# ─────────────────────────────────────────────────────────────────────────────
# Hospital
# ─────────────────────────────────────────────────────────────────────────────

class Hospital(db.Model):
    __tablename__ = "hospitals"

    id                  = db.Column(db.Integer, primary_key=True)
    name                = db.Column(db.String(200), nullable=False)
    address             = db.Column(db.String(300), nullable=False)
    city                = db.Column(db.String(100), nullable=False)
    state               = db.Column(db.String(100), nullable=False)
    lat                 = db.Column(db.Float, nullable=False)
    lng                 = db.Column(db.Float, nullable=False)
    contact_phone       = db.Column(db.String(20))
    contact_email       = db.Column(db.String(150))
    registration_number = db.Column(db.String(100), unique=True)
    is_verified         = db.Column(db.Boolean, default=False)
    created_at          = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    emergency_requests = db.relationship("EmergencyRequest", backref="hospital", lazy=True)

    def __repr__(self):
        return f"<Hospital {self.name}>"


# ─────────────────────────────────────────────────────────────────────────────
# Blood Bank
# ─────────────────────────────────────────────────────────────────────────────

class BloodBank(db.Model):
    __tablename__ = "blood_banks"

    id              = db.Column(db.Integer, primary_key=True)
    name            = db.Column(db.String(200), nullable=False)
    address         = db.Column(db.String(300), nullable=False)
    city            = db.Column(db.String(100), nullable=False)
    state           = db.Column(db.String(100), nullable=False)
    lat             = db.Column(db.Float, nullable=False)
    lng             = db.Column(db.Float, nullable=False)
    contact_phone   = db.Column(db.String(20))
    contact_email   = db.Column(db.String(150))
    license_number  = db.Column(db.String(100), unique=True)
    is_verified     = db.Column(db.Boolean, default=False)
    is_active       = db.Column(db.Boolean, default=True)
    created_at      = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    # Relationships
    inventory            = db.relationship("Inventory", backref="blood_bank", lazy=True)
    inventory_transactions = db.relationship("InventoryTransaction", backref="blood_bank", lazy=True)
    emergency_responses  = db.relationship("EmergencyResponse", backref="blood_bank", lazy=True)
    notifications        = db.relationship("Notification",
                                           foreign_keys="Notification.recipient_id",
                                           primaryjoin="and_(Notification.recipient_id==BloodBank.id, "
                                                       "Notification.recipient_type=='bloodbank')",
                                           lazy=True)
    demand_history       = db.relationship("DemandHistory", backref="blood_bank", lazy=True)
    low_stock_thresholds = db.relationship("LowStockThreshold", backref="blood_bank", lazy=True)

    def __repr__(self):
        return f"<BloodBank {self.name}>"


# ─────────────────────────────────────────────────────────────────────────────
# Inventory
# ─────────────────────────────────────────────────────────────────────────────

class Inventory(db.Model):
    __tablename__ = "inventory"

    id              = db.Column(db.Integer, primary_key=True)
    blood_bank_id   = db.Column(db.Integer, db.ForeignKey("blood_banks.id"), nullable=False)
    blood_group     = db.Column(db.String(5), nullable=False)   # A+, A-, …
    component       = db.Column(db.String(50), nullable=False)  # Packed RBC, …
    units_available = db.Column(db.Integer, default=0, nullable=False)
    units_reserved  = db.Column(db.Integer, default=0, nullable=False)
    expiry_date     = db.Column(db.Date, nullable=True)
    collection_date = db.Column(db.Date, nullable=True)
    last_updated    = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                                onupdate=lambda: datetime.now(timezone.utc))

    @property
    def effective_units(self):
        """Units actually free to allocate."""
        return max(0, self.units_available - self.units_reserved)

    @property
    def status_label(self):
        u = self.effective_units
        if u == 0:
            return "critical"
        elif u <= 5:
            return "low"
        return "ok"

    def __repr__(self):
        return f"<Inventory {self.blood_group} {self.component} @ bank {self.blood_bank_id}>"


# ─────────────────────────────────────────────────────────────────────────────
# Inventory Transaction
# ─────────────────────────────────────────────────────────────────────────────

class InventoryTransaction(db.Model):
    __tablename__ = "inventory_transactions"

    id               = db.Column(db.Integer, primary_key=True)
    blood_bank_id    = db.Column(db.Integer, db.ForeignKey("blood_banks.id"), nullable=False)
    blood_group      = db.Column(db.String(5), nullable=False)
    component        = db.Column(db.String(50), nullable=False)
    transaction_type = db.Column(db.String(30), nullable=False)  # Donation | Issue | Discard …
    units            = db.Column(db.Integer, nullable=False)
    reference_id     = db.Column(db.Integer, nullable=True)      # e.g. emergency_request id
    notes            = db.Column(db.Text, nullable=True)
    performed_by     = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    timestamp        = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    performed_by_user = db.relationship("User", foreign_keys=[performed_by])

    def __repr__(self):
        return f"<Transaction {self.transaction_type} {self.units}u {self.blood_group}>"


# ─────────────────────────────────────────────────────────────────────────────
# Emergency Request
# ─────────────────────────────────────────────────────────────────────────────

class EmergencyRequest(db.Model):
    __tablename__ = "emergency_requests"

    id               = db.Column(db.Integer, primary_key=True)
    hospital_id      = db.Column(db.Integer, db.ForeignKey("hospitals.id"), nullable=False)
    blood_group      = db.Column(db.String(5), nullable=False)
    component        = db.Column(db.String(50), nullable=False)
    units_required   = db.Column(db.Integer, nullable=False)
    urgency_level    = db.Column(db.String(20), nullable=False)   # Critical | High | Medium
    required_by_time = db.Column(db.DateTime, nullable=True)
    patient_info     = db.Column(db.String(200), nullable=True)
    additional_notes = db.Column(db.Text, nullable=True)
    status           = db.Column(db.String(20), default="Pending")  # Pending | Matched | Fulfilled | Cancelled
    created_at       = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at       = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                                 onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    responses = db.relationship("EmergencyResponse", backref="request", lazy=True)

    def __repr__(self):
        return f"<EmergencyRequest #{self.id} {self.blood_group} [{self.status}]>"


# ─────────────────────────────────────────────────────────────────────────────
# Emergency Response
# ─────────────────────────────────────────────────────────────────────────────

class EmergencyResponse(db.Model):
    __tablename__ = "emergency_responses"

    id                  = db.Column(db.Integer, primary_key=True)
    request_id          = db.Column(db.Integer, db.ForeignKey("emergency_requests.id"), nullable=False)
    blood_bank_id       = db.Column(db.Integer, db.ForeignKey("blood_banks.id"), nullable=False)
    availability_status = db.Column(db.String(20), nullable=False)  # Available | Partial | Unavailable
    units_available     = db.Column(db.Integer, default=0)
    units_committed     = db.Column(db.Integer, default=0)
    verified_by         = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    notes               = db.Column(db.Text, nullable=True)
    responded_at        = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    verified_by_user = db.relationship("User", foreign_keys=[verified_by])

    def __repr__(self):
        return f"<EmergencyResponse req#{self.request_id} bank#{self.blood_bank_id} [{self.availability_status}]>"


# ─────────────────────────────────────────────────────────────────────────────
# Notification
# ─────────────────────────────────────────────────────────────────────────────

class Notification(db.Model):
    __tablename__ = "notifications"

    id              = db.Column(db.Integer, primary_key=True)
    recipient_type  = db.Column(db.String(20), nullable=False)  # bloodbank | hospital
    recipient_id    = db.Column(db.Integer, nullable=False)
    type            = db.Column(db.String(30), nullable=False)  # Emergency | Low Stock | Expiry | System | Response
    title           = db.Column(db.String(200), nullable=False)
    message         = db.Column(db.Text, nullable=False)
    reference_id    = db.Column(db.Integer, nullable=True)      # e.g. emergency_request id
    is_read         = db.Column(db.Boolean, default=False)
    is_dismissed    = db.Column(db.Boolean, default=False)
    created_at      = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"<Notification [{self.type}] → {self.recipient_type}#{self.recipient_id}>"


# ─────────────────────────────────────────────────────────────────────────────
# Low Stock Threshold
# ─────────────────────────────────────────────────────────────────────────────

class LowStockThreshold(db.Model):
    __tablename__ = "low_stock_thresholds"

    id              = db.Column(db.Integer, primary_key=True)
    blood_bank_id   = db.Column(db.Integer, db.ForeignKey("blood_banks.id"), nullable=False)
    blood_group     = db.Column(db.String(5), nullable=False)
    component       = db.Column(db.String(50), nullable=False)
    threshold_units = db.Column(db.Integer, default=5, nullable=False)
    alert_active    = db.Column(db.Boolean, default=True)

    def __repr__(self):
        return f"<Threshold {self.blood_group} {self.component} ≤{self.threshold_units}>"


# ─────────────────────────────────────────────────────────────────────────────
# Demand History  (monthly aggregates for ML prediction)
# ─────────────────────────────────────────────────────────────────────────────

class DemandHistory(db.Model):
    __tablename__ = "demand_history"

    id            = db.Column(db.Integer, primary_key=True)
    blood_bank_id = db.Column(db.Integer, db.ForeignKey("blood_banks.id"), nullable=False)
    blood_group   = db.Column(db.String(5), nullable=False)
    component     = db.Column(db.String(50), nullable=False)
    month         = db.Column(db.Integer, nullable=False)   # 1-12
    year          = db.Column(db.Integer, nullable=False)
    units_issued  = db.Column(db.Integer, default=0)
    units_received= db.Column(db.Integer, default=0)

    __table_args__ = (
        db.UniqueConstraint("blood_bank_id", "blood_group", "component", "month", "year",
                            name="uq_demand_history"),
    )

    def __repr__(self):
        return f"<DemandHistory {self.blood_group} {self.month}/{self.year}>"
