from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app.models import Hospital, EmergencyRequest, EmergencyResponse, Notification, BloodBank, Inventory
from app import db
from app.utils.geo import haversine_km
from functools import wraps

hospital_bp = Blueprint("hospital", __name__, template_folder="../templates/hospital")


def hospital_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != "hospital":
            flash("Access restricted to hospital accounts.", "danger")
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated


def _get_hospital_context(hospital_id):
    unread_count = Notification.query.filter_by(
        recipient_type="hospital", recipient_id=hospital_id, is_read=False
    ).count()
    return dict(unread_count=unread_count)


@hospital_bp.route("/dashboard")
@login_required
@hospital_required
def dashboard():
    hospital = Hospital.query.get(current_user.entity_id)
    active_requests = EmergencyRequest.query.filter_by(
        hospital_id=hospital.id, status="Pending"
    ).order_by(EmergencyRequest.created_at.desc()).all()
    recent_requests = EmergencyRequest.query.filter_by(
        hospital_id=hospital.id
    ).order_by(EmergencyRequest.created_at.desc()).limit(10).all()
    ctx = _get_hospital_context(hospital.id)
    return render_template("hospital/dashboard.html",
                           hospital=hospital,
                           active_requests=active_requests,
                           recent_requests=recent_requests,
                           **ctx)


@hospital_bp.route("/request/<int:req_id>")
@login_required
@hospital_required
def request_detail(req_id):
    hospital = Hospital.query.get(current_user.entity_id)
    req = EmergencyRequest.query.filter_by(
        id=req_id, hospital_id=hospital.id
    ).first_or_404()
    responses = EmergencyResponse.query.filter_by(request_id=req_id).all()
    ctx = _get_hospital_context(hospital.id)
    return render_template("hospital/request_detail.html",
                           hospital=hospital, req=req, responses=responses, **ctx)


@hospital_bp.route("/requests")
@login_required
@hospital_required
def requests():
    hospital = Hospital.query.get(current_user.entity_id)
    status_filter = request.args.get("status", "")
    q = EmergencyRequest.query.filter_by(hospital_id=hospital.id)
    if status_filter:
        q = q.filter_by(status=status_filter)
    all_requests = q.order_by(EmergencyRequest.created_at.desc()).all()
    ctx = _get_hospital_context(hospital.id)
    return render_template("hospital/requests.html", hospital=hospital,
                           requests=all_requests, status_filter=status_filter, **ctx)


@hospital_bp.route("/blood-banks")
@login_required
@hospital_required
def blood_banks():
    hospital = Hospital.query.get(current_user.entity_id)
    all_banks = BloodBank.query.filter_by(is_active=True, is_verified=True).all()
    # Annotate with distance
    banks_with_dist = []
    for b in all_banks:
        dist = haversine_km(hospital.lat, hospital.lng, b.lat, b.lng)
        banks_with_dist.append((b, round(dist, 1)))
    banks_with_dist.sort(key=lambda x: x[1])
    ctx = _get_hospital_context(hospital.id)
    return render_template("hospital/blood_banks.html", hospital=hospital,
                           banks_with_dist=banks_with_dist, **ctx)


@hospital_bp.route("/notifications")
@login_required
@hospital_required
def notifications():
    hospital = Hospital.query.get(current_user.entity_id)
    notifs = Notification.query.filter_by(
        recipient_type="hospital", recipient_id=hospital.id
    ).order_by(Notification.created_at.desc()).all()
    Notification.query.filter_by(
        recipient_type="hospital", recipient_id=hospital.id, is_read=False
    ).update({"is_read": True})
    db.session.commit()
    ctx = _get_hospital_context(hospital.id)
    return render_template("hospital/notifications.html",
                           hospital=hospital, notifications=notifs, **ctx)
