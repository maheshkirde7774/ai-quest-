from functools import wraps
from datetime import timezone

from flask import jsonify
from flask_login import current_user

from extensions import db, socketio
from models import ActivityLog


def iso_utc(value):
    if not value:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def admin_required(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated or getattr(current_user, "role", "") not in (
            "admin", "super-admin"
        ):
            return jsonify(error="Administrator access required."), 403
        return function(*args, **kwargs)

    return wrapped


def team_required(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated or getattr(current_user, "role", "") != "team":
            return jsonify(error="Team login required."), 403
        if current_user.status in ("DISABLED", "DISQUALIFIED"):
            return jsonify(error="This team is not allowed to continue."), 403
        return function(*args, **kwargs)

    return wrapped


def audit(action, target="", metadata=None):
    admin_id = current_user.id if current_user.is_authenticated and getattr(
        current_user, "role", ""
    ) in ("admin", "super-admin") else None
    db.session.add(
        ActivityLog(
            admin_id=admin_id,
            action=action,
            target=str(target),
            metadata_json=metadata or {},
        )
    )


def emit_activity(message, category="event"):
    socketio.emit("activity", {"message": message, "category": category}, room="admins")


def emit_leaderboard():
    from utils.scoring import leaderboard_rows

    socketio.emit("leaderboard", leaderboard_rows(), room="participants")