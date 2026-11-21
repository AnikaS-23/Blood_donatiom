"""
app/api/routes.py
─────────────────
JSON API endpoints for inventory, emergency requests, notifications, geo-search.
"""

from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
from app import db
from app.models import (Inventory, EmergencyRequest, EmergencyResponse,
                         BloodBank, Hospital, Notification, BLOOD_GROUPS, BLOOD_COMPONENTS)
from app.utils.geo import haversine_km
from app.utils.alerts import check_low_stock, check_expiring_units, generate_startup_alerts
from app import socketio
from datetime import datetime, timezone, timedelta

api_bp = Blueprint("api", __name__)


# ─── Inventory ───────────────────────────────────────────────────────────────

@api_bp.route("/inventory/<int:bank_id>")
@login_required
def get_inventory(bank_id):
    items = Inventory.query.filter_by(blood_bank_id=bank_id).all()
    data = [{
        "id": i.id,
        "blood_group": i.blood_group,
        "component": i.component,
        "units_available": i.units_available,
        "units_reserved": i.units_reserved,
        "effective_units": i.effective_units,
        "status": i.status_label,
        "expiry_date": i.expiry_date.isoformat() if i.expiry_date else None,
    } for i in items]
    return jsonify(data)


@api_bp.route("/inventory/update", methods=["POST"])
@login_required
def update_inventory():
    if current_user.role != "bloodbank":
        return jsonify({"error": "Forbidden"}), 403

    payload = request.get_json()
    item = Inventory.query.get(payload.get("id"))
    if not item or item.blood_bank_id != current_user.entity_id:
        return jsonify({"error": "Not found"}), 404

    item.units_available = int(payload.get("units_available", item.units_available))
    item.last_updated = datetime.now(timezone.utc)
    db.session.commit()

    # Trigger low-stock check
    check_low_stock(item.blood_bank_id, item.blood_group, item.component, item.units_available)

    return jsonify({"ok": True, "effective_units": item.effective_units, "status": item.status_label})


# ─── Emergency Requests ───────────────────────────────────────────────────────

@api_bp.route("/request/new", methods=["POST"])
@login_required
def new_request():
    if current_user.role != "hospital":
        return jsonify({"error": "Forbidden"}), 403

    payload = request.get_json()
    hospital = Hospital.query.get(current_user.entity_id)

    req = EmergencyRequest(
        hospital_id      = hospital.id,
        blood_group      = payload["blood_group"],
        component        = payload["component"],
        units_required   = int(payload["units_required"]),
        urgency_level    = payload["urgency_level"],
        required_by_time = datetime.fromisoformat(payload["required_by_time"]) if payload.get("required_by_time") else None,
        patient_info     = payload.get("patient_info", ""),
        additional_notes = payload.get("additional_notes", ""),
        status           = "Pending",
    )
    db.session.add(req)
    db.session.commit()

    # Find nearby blood banks
    radius_km = 50
    nearby_banks = []
    for bank in BloodBank.query.filter_by(is_active=True, is_verified=True).all():
        dist = haversine_km(hospital.lat, hospital.lng, bank.lat, bank.lng)
        if dist <= radius_km:
            nearby_banks.append((bank, dist))

    # For each nearby bank: check inventory + create notification + push SocketIO
    for bank, dist in nearby_banks:
        inv = Inventory.query.filter_by(
            blood_bank_id=bank.id,
            blood_group=req.blood_group,
            component=req.component
        ).first()

        potentially_available = inv and inv.effective_units >= req.units_required
        status_hint = "Potentially Available – Take Action" if potentially_available else "Check Inventory"

        notif = Notification(
            recipient_type = "bloodbank",
            recipient_id   = bank.id,
            type           = "Emergency",
            title          = f"🚨 Emergency: {req.blood_group} {req.component}",
            message        = (f"{hospital.name} needs {req.units_required} units of "
                              f"{req.blood_group} {req.component}. "
                              f"Urgency: {req.urgency_level}. "
                              f"Distance: {dist:.1f} km. {status_hint}"),
            reference_id   = req.id,
        )
        db.session.add(notif)
        db.session.flush()

        # Emit SocketIO event to blood bank room
        socketio.emit("emergency_alert", {
            "request_id"    : req.id,
            "hospital_name" : hospital.name,
            "blood_group"   : req.blood_group,
            "component"     : req.component,
            "units_required": req.units_required,
            "urgency_level" : req.urgency_level,
            "required_by"   : req.required_by_time.isoformat() if req.required_by_time else None,
            "status_hint"   : status_hint,
            "notification_id": notif.id,
        }, room=f"bloodbank_{bank.id}")

    db.session.commit()
    return jsonify({"ok": True, "request_id": req.id, "notified_banks": len(nearby_banks)})


@api_bp.route("/request/<int:req_id>/respond", methods=["POST"])
@login_required
def respond_request(req_id):
    if current_user.role != "bloodbank":
        return jsonify({"error": "Forbidden"}), 403

    payload = request.get_json()
    req = EmergencyRequest.query.get_or_404(req_id)
    bank_id = current_user.entity_id

    response = EmergencyResponse(
        request_id          = req.id,
        blood_bank_id       = bank_id,
        availability_status = payload["availability_status"],
        units_available     = int(payload.get("units_available", 0)),
        units_committed     = int(payload.get("units_committed", 0)),
        verified_by         = current_user.id,
        notes               = payload.get("notes", ""),
    )
    db.session.add(response)

    # Update request status
    if payload["availability_status"] in ("Available", "Partial"):
        req.status = "Matched"

    # Notify hospital
    bank = BloodBank.query.get(bank_id)
    notif = Notification(
        recipient_type = "hospital",
        recipient_id   = req.hospital_id,
        type           = "Response",
        title          = f"Response from {bank.name}",
        message        = (f"{bank.name} responded: {payload['availability_status']}. "
                          f"Units available: {payload.get('units_available', 0)}."),
        reference_id   = req.id,
    )
    db.session.add(notif)
    db.session.commit()

    socketio.emit("response_received", {
        "request_id"         : req.id,
        "bank_name"          : bank.name,
        "availability_status": payload["availability_status"],
        "units_available"    : payload.get("units_available", 0),
    }, room=f"hospital_{req.hospital_id}")

    return jsonify({"ok": True})


# ─── Nearby Banks ─────────────────────────────────────────────────────────────

@api_bp.route("/nearby-banks")
@login_required
def nearby_banks():
    lat  = float(request.args.get("lat", 0))
    lng  = float(request.args.get("lng", 0))
    radius = float(request.args.get("radius_km", 50))

    results = []
    for bank in BloodBank.query.filter_by(is_active=True, is_verified=True).all():
        dist = haversine_km(lat, lng, bank.lat, bank.lng)
        if dist <= radius:
            results.append({
                "id": bank.id, "name": bank.name,
                "address": bank.address, "city": bank.city,
                "phone": bank.contact_phone,
                "distance_km": round(dist, 2),
            })
    results.sort(key=lambda x: x["distance_km"])
    return jsonify(results)


# ─── Notifications ────────────────────────────────────────────────────────────

@api_bp.route("/notifications/unread")
@login_required
def unread_notifications():
    rtype = current_user.role if current_user.role in ("hospital", "bloodbank") else None
    if not rtype:
        return jsonify([])
    notifs = Notification.query.filter_by(
        recipient_type=rtype,
        recipient_id=current_user.entity_id,
        is_read=False,
    ).order_by(Notification.created_at.desc()).all()
    return jsonify([{
        "id": n.id, "type": n.type, "title": n.title,
        "message": n.message, "reference_id": n.reference_id,
        "created_at": n.created_at.isoformat(),
    } for n in notifs])


@api_bp.route("/notifications/<int:notif_id>/dismiss", methods=["POST"])
@login_required
def dismiss_notification(notif_id):
    notif = Notification.query.get_or_404(notif_id)
    notif.is_dismissed = True
    notif.is_read = True
    db.session.commit()
    return jsonify({"ok": True})


# ─── Dashboard Stats (AJAX) ───────────────────────────────────────────────────

@api_bp.route("/dashboard-stats/<int:bank_id>")
@login_required
def dashboard_stats(bank_id):
    if current_user.role != "bloodbank" or current_user.entity_id != bank_id:
        return jsonify({"error": "Forbidden"}), 403

    from datetime import date, timedelta
    today = date.today()
    warn_cutoff = today + timedelta(days=7)

    inventory = Inventory.query.filter_by(blood_bank_id=bank_id).all()
    total_units = sum(i.units_available for i in inventory)
    low_stock_count = sum(1 for i in inventory if i.status_label in ("low", "critical"))
    expiring_count = Inventory.query.filter(
        Inventory.blood_bank_id == bank_id,
        Inventory.expiry_date != None,
        Inventory.expiry_date <= warn_cutoff,
        Inventory.expiry_date >= today,
        Inventory.units_available > 0,
    ).count()
    active_emergencies = EmergencyRequest.query.filter_by(status="Pending").count()
    unread_notifs = Notification.query.filter_by(
        recipient_type="bloodbank", recipient_id=bank_id, is_read=False
    ).count()

    return jsonify({
        "total_units": total_units,
        "low_stock_count": low_stock_count,
        "expiring_soon_count": expiring_count,
        "active_emergencies": active_emergencies,
        "unread_notifications": unread_notifs,
    })


# ─── Admin: Manual Alert Trigger ─────────────────────────────────────────────

@api_bp.route("/admin/run-checks")
@login_required
def run_checks():
    if current_user.role != "admin":
        return jsonify({"error": "Forbidden"}), 403

    from app import create_app as _create_app
    import flask
    app = flask.current_app._get_current_object()

    from app.utils.alerts import check_expiring_units, generate_startup_alerts
    before = Notification.query.count()
    check_expiring_units(app)
    generate_startup_alerts(app)
    after = Notification.query.count()

    return jsonify({"ok": True, "notifications_created": after - before})
