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
    active = Round.query.filter_by(status="ACTIVE").first()
    if action == "start":
        if active and active.id != event_round.id:
            return jsonify(error=f"Round {active.number} is already active."), 409
        if event_round.status not in ("READY", "ACTIVE"):
            return jsonify(error="Unlock this round before starting it."), 409
        event_round.status = "ACTIVE"
        event_round.started_at = event_round.started_at or utcnow()
        label = "started"
    elif action == "pause":
        if event_round.status != "ACTIVE":
            return jsonify(error="Only an active round can be paused."), 409
        event_round.status = "READY"
        label = "paused"
    elif action == "end":
        if event_round.status != "ACTIVE":
            return jsonify(error="Only an active round can be ended."), 409
        event_round.status = "COMPLETED"
        event_round.ended_at = utcnow()
        for session in RoundSession.query.filter_by(round_id=event_round.id, status="ACTIVE"):
            session.ended_at = event_round.ended_at
            session.status = "COMPLETED"
        next_round = Round.query.filter_by(number=event_round.number + 1).first()
        if next_round and next_round.status == "LOCKED":
            next_round.status = "READY"
        label = "ended"
    elif action == "unlock":
        if event_round.status != "LOCKED":
            return jsonify(error="Only a locked round can be unlocked."), 409
        previous = Round.query.filter_by(number=event_round.number - 1).first()
        if event_round.number > 1 and (not previous or previous.status != "COMPLETED"):
            return jsonify(error="Complete the previous round first."), 409
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
    event_round = db.session.get(Round, round_id)
    session = RoundSession.query.filter_by(
        team_id=current_user.id, round_id=round_id, status="ACTIVE"
    ).first()
    if not event_round or event_round.status != "ACTIVE" or not session:
        return jsonify(error="No active team session for this round."), 409
    session.ended_at = utcnow()
    session.status = "COMPLETED"
    if event_round.number == 3:
        current_user.status = "COMPLETED"
    audit("Team round completed", current_user.team_id, {"round": event_round.number})
    db.session.commit()
    emit_activity(f"{current_user.team_id} completed Round {event_round.number}", "round")
    emit_leaderboard()
    return jsonify(completed_at=iso_utc(session.ended_at))
