from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_required, current_user
from app.models import User, Hospital, BloodBank
from app import db
from functools import wraps

admin_bp = Blueprint("admin", __name__, template_folder="../templates/admin")


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != "admin":
            flash("Admin access required.", "danger")
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated


@admin_bp.route("/dashboard")
@login_required
@admin_required
def dashboard():
    total_hospitals = Hospital.query.count()
    total_banks     = BloodBank.query.count()
    total_users     = User.query.count()
    return render_template(
        "admin/dashboard.html",
        total_hospitals=total_hospitals,
        total_banks=total_banks,
        total_users=total_users,
    )


@admin_bp.route("/hospitals")
@login_required
@admin_required
def hospitals():
    all_hospitals = Hospital.query.order_by(Hospital.name).all()
    return render_template("admin/hospitals.html", hospitals=all_hospitals)


@admin_bp.route("/hospitals/<int:h_id>/toggle", methods=["POST"])
@login_required
@admin_required
def toggle_hospital(h_id):
    h = Hospital.query.get_or_404(h_id)
    h.is_verified = not h.is_verified
    db.session.commit()
    flash(f"Hospital '{ h.name }' {'verified' if h.is_verified else 'unverified'}.", "success")
    return redirect(url_for("admin.hospitals"))


@admin_bp.route("/blood-banks")
@login_required
@admin_required
def blood_banks():
    all_banks = BloodBank.query.order_by(BloodBank.name).all()
    return render_template("admin/blood_banks.html", blood_banks=all_banks)


@admin_bp.route("/blood-banks/<int:b_id>/toggle", methods=["POST"])
@login_required
@admin_required
def toggle_blood_bank(b_id):
    b = BloodBank.query.get_or_404(b_id)
    b.is_active = not b.is_active
    db.session.commit()
    flash(f"Blood bank '{ b.name }' {'activated' if b.is_active else 'deactivated'}.", "success")
    return redirect(url_for("admin.blood_banks"))


@admin_bp.route("/users")
@login_required
@admin_required
def users():
    all_users = User.query.order_by(User.created_at.desc()).all()
    return render_template("admin/users.html", users=all_users)

