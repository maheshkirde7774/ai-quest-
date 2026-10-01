from flask import Blueprint, jsonify
from flask_login import current_user

from extensions import db
from models import Round, RoundSession, utcnow
from routes.common import admin_required, audit, emit_activity, emit_leaderboard, iso_utc, team_required

rounds_bp = Blueprint("rounds", __name__)


@rounds_bp.get("/api/rounds")
@admin_required
def list_rounds():
    return jsonify([
        {"id": item.id, "number": item.number, "name": item.name, "status": item.status,
         "started_at": iso_utc(item.started_at), "ended_at": iso_utc(item.ended_at)}
        for item in Round.query.order_by(Round.number)
    ])


@rounds_bp.post("/api/rounds/<int:round_id>/<action>")
@admin_required
def control_round(round_id, action):
    event_round = db.session.get(Round, round_id)
    if not event_round:
        return jsonify(error="Round not found."), 404
    from services.event import event_config
    event = event_config()
    if event.results_locked:
        return jsonify(error="Results are locked."), 409
    active = Round.query.filter_by(status="ACTIVE").first()
    if action in ("start", "resume"):
        if event_round.status not in ("READY", "ACTIVE", "PAUSED"):
            return jsonify(error="Unlock this round before starting it."), 409
        was_paused = event_round.status == "PAUSED"
        event.active = True
        event_round.status = "ACTIVE"
        event_round.started_at = event_round.started_at or utcnow()
        label = "resumed" if action == "resume" or was_paused else "started"
    elif action == "pause":
        if event_round.status != "ACTIVE":
            return jsonify(error="Only an active round can be paused."), 409
        event_round.status = "PAUSED"
        label = "paused"
    elif action == "end":
        if event_round.status not in ("ACTIVE", "PAUSED"):
            return jsonify(error="Only an active or paused round can be ended."), 409
        event_round.status = "ENDED"
        event_round.ended_at = utcnow()
        next_round = Round.query.filter_by(number=event_round.number + 1).first()
        if next_round and next_round.status == "LOCKED":
            next_round.status = "READY"
        label = "ended"
    elif action == "unlock":
        if event_round.status != "LOCKED":
            return jsonify(error="Only a locked round can be unlocked."), 409
        event_round.status = "READY"
        label = "unlocked"
    else:
        return jsonify(error="Unknown round action."), 404
    audit(f"Round {label}", f"Round {event_round.number}")
    db.session.commit()
    emit_activity(f"Round {event_round.number} {label}", "round")
    emit_leaderboard()
    return jsonify(status=event_round.status)


@rounds_bp.post("/api/team/rounds/<int:round_id>/complete")
@team_required
def complete_team_round(round_id):
    return jsonify(error="Round completion is recorded automatically after the challenge."), 409
