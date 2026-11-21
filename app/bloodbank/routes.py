from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from app.models import (BloodBank, Inventory, InventoryTransaction,
                         EmergencyRequest, EmergencyResponse, Notification,
                         LowStockThreshold, BLOOD_GROUPS, BLOOD_COMPONENTS)
from app import db
from app.utils.alerts import check_low_stock
from functools import wraps
from datetime import datetime, date, timedelta, timezone
from sqlalchemy import func

bloodbank_bp = Blueprint("bloodbank", __name__, template_folder="../templates/bloodbank")


def bloodbank_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != "bloodbank":
            flash("Access restricted to blood bank accounts.", "danger")
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated


# ─── Helper: get bank + emergency context ────────────────────────────────────

def _get_bank_context(bank_id):
    """Return common sidebar context for blood bank templates."""
    unread_count = Notification.query.filter_by(
        recipient_type="bloodbank", recipient_id=bank_id, is_read=False
    ).count()
    emergency_notifs = Notification.query.filter_by(
        recipient_type="bloodbank", recipient_id=bank_id,
        type="Emergency", is_dismissed=False
    ).order_by(Notification.created_at.desc()).all()
    active_emergencies = EmergencyRequest.query.filter_by(status="Pending").count()
    return dict(unread_count=unread_count,
                emergency_notifs=emergency_notifs,
                active_emergencies=active_emergencies)


# ─── Dashboard ────────────────────────────────────────────────────────────────

@bloodbank_bp.route("/dashboard")
@login_required
@bloodbank_required
def dashboard():
    bank = BloodBank.query.get(current_user.entity_id)
    inventory = Inventory.query.filter_by(blood_bank_id=bank.id).all()
    total_units = sum(i.units_available for i in inventory)
    low_stock   = [i for i in inventory if i.status_label in ("low", "critical")]

    today = date.today()
    warn_cutoff = today + timedelta(days=7)
    expiring_soon = Inventory.query.filter(
        Inventory.blood_bank_id == bank.id,
        Inventory.expiry_date != None,
        Inventory.expiry_date <= warn_cutoff,
        Inventory.expiry_date >= today,
        Inventory.units_available > 0,
    ).order_by(Inventory.expiry_date).all()

    expired = Inventory.query.filter(
        Inventory.blood_bank_id == bank.id,
        Inventory.expiry_date != None,
        Inventory.expiry_date < today,
        Inventory.units_available > 0,
    ).all()

    ctx = _get_bank_context(bank.id)
    return render_template("bloodbank/dashboard.html",
                           bank=bank, inventory=inventory,
                           total_units=total_units, low_stock=low_stock,
                           expiring_soon=expiring_soon, expired=expired, **ctx)


# ─── Inventory ────────────────────────────────────────────────────────────────

@bloodbank_bp.route("/inventory")
@login_required
@bloodbank_required
def inventory():
    bank  = BloodBank.query.get(current_user.entity_id)
    today = date.today()

    # Apply optional filters from query params
    filter_bg   = request.args.get("bg", "")
    filter_comp = request.args.get("comp", "")
    filter_status = request.args.get("status", "")

    q = Inventory.query.filter_by(blood_bank_id=bank.id)
    if filter_bg:   q = q.filter_by(blood_group=filter_bg)
    if filter_comp: q = q.filter_by(component=filter_comp)
    items = q.order_by(Inventory.blood_group, Inventory.component).all()

    # Apply status filter client-side-friendly (after query)
    if filter_status:
        items = [i for i in items if i.status_label == filter_status]

    # Expiry summary
    warn_cutoff   = today + timedelta(days=7)
    expiring_soon = [i for i in items if i.expiry_date and i.expiry_date <= warn_cutoff
                     and i.expiry_date >= today and i.units_available > 0]
    expired       = [i for i in items if i.expiry_date and i.expiry_date < today
                     and i.units_available > 0]

    # Recent transactions (last 20)
    recent_txns = InventoryTransaction.query.filter_by(
        blood_bank_id=bank.id
    ).order_by(InventoryTransaction.timestamp.desc()).limit(20).all()

    # Summary stats
    total_units = sum(i.units_available for i in
                      Inventory.query.filter_by(blood_bank_id=bank.id).all())
    low_stock_count = Inventory.query.filter_by(blood_bank_id=bank.id).filter(
        Inventory.units_available <= 5
    ).count()

    ctx = _get_bank_context(bank.id)
    return render_template("bloodbank/inventory.html",
                           bank=bank,
                           inventory=items,
                           expiring_soon=expiring_soon,
                           expired=expired,
                           recent_txns=recent_txns,
                           total_units=total_units,
                           low_stock_count=low_stock_count,
                           today=today,
                           blood_groups=BLOOD_GROUPS,
                           components=BLOOD_COMPONENTS,
                           filter_bg=filter_bg,
                           filter_comp=filter_comp,
                           filter_status=filter_status,
                           **ctx)


# ─── Add Stock (POST via AJAX or form) ───────────────────────────────────────

@bloodbank_bp.route("/inventory/add", methods=["POST"])
@login_required
@bloodbank_required
def inventory_add():
    bank        = BloodBank.query.get(current_user.entity_id)
    blood_group = request.form.get("blood_group", "").strip()
    component   = request.form.get("component", "").strip()
    units       = int(request.form.get("units", 0))
    expiry_str  = request.form.get("expiry_date", "")
    collect_str = request.form.get("collection_date", "")
    notes       = request.form.get("notes", "").strip()
    txn_type    = request.form.get("transaction_type", "Donation")

    if not blood_group or not component or units <= 0:
        flash("Please fill in all required fields with valid values.", "danger")
        return redirect(url_for("bloodbank.inventory"))

    # Find or create inventory record
    inv = Inventory.query.filter_by(
        blood_bank_id=bank.id,
        blood_group=blood_group,
        component=component
    ).first()

    expiry_date  = datetime.strptime(expiry_str, "%Y-%m-%d").date() if expiry_str else None
    collect_date = datetime.strptime(collect_str, "%Y-%m-%d").date() if collect_str else date.today()

    if inv:
        inv.units_available += units
        if expiry_date:
            inv.expiry_date = expiry_date
        inv.collection_date = collect_date
        inv.last_updated    = datetime.now(timezone.utc)
    else:
        inv = Inventory(
            blood_bank_id=bank.id,
            blood_group=blood_group,
            component=component,
            units_available=units,
            units_reserved=0,
            expiry_date=expiry_date,
            collection_date=collect_date,
        )
        db.session.add(inv)

    # Record transaction
    txn = InventoryTransaction(
        blood_bank_id    = bank.id,
        blood_group      = blood_group,
        component        = component,
        transaction_type = txn_type,
        units            = units,
        notes            = notes,
        performed_by     = current_user.id,
    )
    db.session.add(txn)
    db.session.commit()

    flash(f"✔ Added {units} unit(s) of {blood_group} {component} successfully.", "success")
    return redirect(url_for("bloodbank.inventory"))


# ─── Issue / Discard Units ───────────────────────────────────────────────────

@bloodbank_bp.route("/inventory/issue", methods=["POST"])
@login_required
@bloodbank_required
def inventory_issue():
    bank        = BloodBank.query.get(current_user.entity_id)
    blood_group = request.form.get("blood_group", "").strip()
    component   = request.form.get("component", "").strip()
    units       = int(request.form.get("units", 0))
    txn_type    = request.form.get("transaction_type", "Issue")
    ref_id_str  = request.form.get("reference_id", "")
    notes       = request.form.get("notes", "").strip()

    if not blood_group or not component or units <= 0:
        flash("Please fill in all required fields.", "danger")
        return redirect(url_for("bloodbank.inventory"))

    inv = Inventory.query.filter_by(
        blood_bank_id=bank.id,
        blood_group=blood_group,
        component=component
    ).first()

    if not inv or inv.units_available < units:
        flash(f"Insufficient units of {blood_group} {component} available.", "danger")
        return redirect(url_for("bloodbank.inventory"))

    inv.units_available -= units
    inv.last_updated     = datetime.now(timezone.utc)

    txn = InventoryTransaction(
        blood_bank_id    = bank.id,
        blood_group      = blood_group,
        component        = component,
        transaction_type = txn_type,
        units            = units,
        reference_id     = int(ref_id_str) if ref_id_str.isdigit() else None,
        notes            = notes,
        performed_by     = current_user.id,
    )
    db.session.add(txn)
    db.session.commit()

    # Check low-stock after deduction
    check_low_stock(bank.id, blood_group, component, inv.units_available)

    action = "issued" if txn_type == "Issue" else "discarded"
    flash(f"✔ {units} unit(s) of {blood_group} {component} {action}.", "success")
    return redirect(url_for("bloodbank.inventory"))


# ─── Inline Quick-Update (AJAX) ──────────────────────────────────────────────

@bloodbank_bp.route("/inventory/quick-update", methods=["POST"])
@login_required
@bloodbank_required
def inventory_quick_update():
    bank    = BloodBank.query.get(current_user.entity_id)
    inv_id  = request.json.get("id")
    new_val = int(request.json.get("units_available", 0))

    inv = Inventory.query.filter_by(id=inv_id, blood_bank_id=bank.id).first()
    if not inv:
        return jsonify({"ok": False, "error": "Not found"}), 404

    old_val = inv.units_available
    diff    = new_val - old_val
    inv.units_available = new_val
    inv.last_updated    = datetime.now(timezone.utc)

    if diff != 0:
        txn = InventoryTransaction(
            blood_bank_id    = bank.id,
            blood_group      = inv.blood_group,
            component        = inv.component,
            transaction_type = "Donation" if diff > 0 else "Issue",
            units            = abs(diff),
            notes            = "Quick update from inventory table",
            performed_by     = current_user.id,
        )
        db.session.add(txn)

    db.session.commit()
    check_low_stock(bank.id, inv.blood_group, inv.component, inv.units_available)

    return jsonify({"ok": True, "status": inv.status_label,
                    "effective_units": inv.effective_units})


# ─── Threshold Update (AJAX) ─────────────────────────────────────────────────

@bloodbank_bp.route("/inventory/threshold", methods=["POST"])
@login_required
@bloodbank_required
def update_threshold():
    bank    = BloodBank.query.get(current_user.entity_id)
    bg      = request.json.get("blood_group")
    comp    = request.json.get("component")
    new_val = int(request.json.get("threshold", 5))

    t = LowStockThreshold.query.filter_by(
        blood_bank_id=bank.id, blood_group=bg, component=comp
    ).first()
    if t:
        t.threshold_units = new_val
    else:
        t = LowStockThreshold(blood_bank_id=bank.id, blood_group=bg,
                              component=comp, threshold_units=new_val)
        db.session.add(t)
    db.session.commit()
    return jsonify({"ok": True})


# ─── Emergency ───────────────────────────────────────────────────────────────

@bloodbank_bp.route("/emergency")
@login_required
@bloodbank_required
def emergency():
    bank     = BloodBank.query.get(current_user.entity_id)
    requests = EmergencyRequest.query.filter_by(status="Pending").order_by(
        EmergencyRequest.created_at.desc()
    ).all()
    ctx = _get_bank_context(bank.id)
    return render_template("bloodbank/emergency.html", bank=bank, requests=requests, **ctx)


@bloodbank_bp.route("/emergency/<int:req_id>")
@login_required
@bloodbank_required
def emergency_detail(req_id):
    bank    = BloodBank.query.get(current_user.entity_id)
    req     = EmergencyRequest.query.get_or_404(req_id)
    # Check bank's matching inventory
    inv_match = Inventory.query.filter_by(
        blood_bank_id=bank.id,
        blood_group=req.blood_group,
        component=req.component
    ).first()
    # Check if this bank already responded
    existing_response = EmergencyResponse.query.filter_by(
        request_id=req_id, blood_bank_id=bank.id
    ).first()
    ctx = _get_bank_context(bank.id)
    return render_template("bloodbank/emergency_detail.html",
                           bank=bank, req=req,
                           inv_match=inv_match,
                           existing_response=existing_response, **ctx)


# ─── Analytics ───────────────────────────────────────────────────────────────

@bloodbank_bp.route("/analytics")
@login_required
@bloodbank_required
def analytics():
    bank = BloodBank.query.get(current_user.entity_id)
    ctx  = _get_bank_context(bank.id)
    return render_template("bloodbank/analytics.html", bank=bank, **ctx)


# ─── Notifications ───────────────────────────────────────────────────────────

@bloodbank_bp.route("/notifications")
@login_required
@bloodbank_required
def notifications():
    bank   = BloodBank.query.get(current_user.entity_id)
    notifs = Notification.query.filter_by(
        recipient_type="bloodbank", recipient_id=bank.id
    ).order_by(Notification.created_at.desc()).all()
    Notification.query.filter_by(
        recipient_type="bloodbank", recipient_id=bank.id, is_read=False
    ).update({"is_read": True})
    db.session.commit()
    ctx = _get_bank_context(bank.id)
    return render_template("bloodbank/notifications.html",
                           bank=bank, notifications=notifs, **ctx)


# ─── Settings ────────────────────────────────────────────────────────────────

@bloodbank_bp.route("/settings")
@login_required
@bloodbank_required
def settings():
    bank = BloodBank.query.get(current_user.entity_id)
    thresholds = {
        (t.blood_group, t.component): t.threshold_units
        for t in LowStockThreshold.query.filter_by(blood_bank_id=bank.id).all()
    }
    ctx = _get_bank_context(bank.id)
    return render_template("bloodbank/settings.html",
                           bank=bank,
                           thresholds=thresholds,
                           blood_groups=BLOOD_GROUPS,
                           components=BLOOD_COMPONENTS, **ctx)
