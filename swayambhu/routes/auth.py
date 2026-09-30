from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_user, logout_user

from extensions import db
from models import Admin, Team
from routes.common import audit

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/")
def index():
    if current_user.is_authenticated:
        if getattr(current_user, "role", "") == "team":
            return redirect(url_for("teams.team_dashboard"))
        return redirect(url_for("admin.dashboard"))
    return redirect(url_for("auth.admin_login"))


@auth_bp.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if current_user.is_authenticated and getattr(current_user, "role", "") in (
        "admin", "super-admin"
    ):
        return redirect(url_for("admin.dashboard"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        admin = Admin.query.filter_by(username=username).first()
        if admin and admin.check_password(password):
            login_user(admin)
            audit("Admin login", admin.username)
            db.session.commit()
            return redirect(url_for("admin.dashboard"))
        flash("Username or password is incorrect.", "error")
    return render_template("admin_login.html")


@auth_bp.route("/team/login", methods=["GET", "POST"])
def team_login():
    if current_user.is_authenticated and getattr(current_user, "role", "") == "team":
        return redirect(url_for("teams.team_dashboard"))
    if request.method == "POST":
        team_id = request.form.get("team_id", "").strip().upper()
        pin = request.form.get("pin", "")
        team = Team.query.filter_by(team_id=team_id).first()
        if team and team.status not in ("DISABLED", "DISQUALIFIED") and team.check_pin(pin):
            login_user(team)
            db.session.commit()
            scan_token = request.form.get("scan", "").strip()
            return redirect(url_for("teams.team_dashboard", scan=scan_token) if scan_token else url_for("teams.team_dashboard"))
        flash("Team ID or PIN is incorrect, or this team is disabled.", "error")
    return render_template("team_login.html", scan_token=request.args.get("scan", ""))


@auth_bp.route("/logout", methods=["POST"])
def logout():
    destination = "auth.team_login" if getattr(current_user, "role", "") == "team" else "auth.admin_login"
    if current_user.is_authenticated:
        if getattr(current_user, "role", "") in ("admin", "super-admin"):
            audit("Admin logout", current_user.username)
        logout_user()
        db.session.commit()
    return redirect(url_for(destination))
