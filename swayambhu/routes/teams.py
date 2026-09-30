from datetime import timezone

from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import func

from extensions import db
from models import Answer, FinalResult, Round, RoundSession, ScanLog, Score, Team, TeamMember, utcnow
from routes.common import admin_required, audit, emit_activity, emit_leaderboard, iso_utc, team_required
from utils.security import new_team_pin

teams_bp = Blueprint("teams", __name__)
TEAM_STATUSES = {"READY", "ACTIVE", "COMPLETED", "DISQUALIFIED", "DISABLED"}


def _team_payload(team):
    return {
        "id": team.id,
        "team_id": team.team_id,
        "team_name": team.team_name,
        "member_1": team.member_1,
        "member_2": team.member_2,
        "member_3": team.member_3,
        "status": team.status,
        "created_at": iso_utc(team.created_at),
        "score": sum(score.points for score in team.scores),
    }


def _next_team_id():
    teams = Team.query.order_by(Team.id.desc()).all()
    used = {team.team_id for team in teams}
    number = 1
    while f"AIQ-{number:03d}" in used:
        number += 1
    return f"AIQ-{number:03d}"


@teams_bp.get("/team")
@login_required
def team_dashboard():
    if getattr(current_user, "role", "") != "team":
        return redirect(url_for("admin.dashboard"))
    return render_template("team_dashboard.html")


@teams_bp.get("/scan/<token>")
def open_scanned_qr(token):
    if getattr(current_user, "role", "") == "team":
        return redirect(url_for("teams.team_dashboard", scan=token))
    return redirect(url_for("auth.team_login", scan=token))


@teams_bp.get("/api/teams")
@admin_required
def list_teams():
    term = request.args.get("q", "").strip()
    query = Team.query
    if term:
        like = f"%{term}%"
        query = query.filter(db.or_(Team.team_id.ilike(like), Team.team_name.ilike(like)))
    return jsonify([_team_payload(team) for team in query.order_by(Team.id).all()])


@teams_bp.post("/api/teams")
@admin_required
def create_team():
    data = request.get_json(silent=True) or request.form
    name = str(data.get("team_name", "")).strip()
    if not name or len(name) > 120:
        return jsonify(error="Team name is required (120 characters maximum)."), 400
    pin = str(data.get("login_pin", "")).strip() or new_team_pin()
    if not pin.isdigit() or not 4 <= len(pin) <= 12:
        return jsonify(error="PIN must contain 4 to 12 digits."), 400
    team = Team(
        team_id=_next_team_id(),
        team_name=name,
        member_1=str(data.get("member_1", "")).strip()[:100],
        member_2=str(data.get("member_2", "")).strip()[:100],
        member_3=str(data.get("member_3", "")).strip()[:100],
    )
    team.set_pin(pin)
    team.members = [
        TeamMember(name=value, position=position)
        for position, value in enumerate((team.member_1, team.member_2, team.member_3), start=1)
        if value
    ]
    db.session.add(team)
    audit("Team created", team.team_id)
    db.session.commit()
    emit_activity(f"{team.team_id} team created", "team")
    emit_leaderboard()
    return jsonify(team=_team_payload(team), login_pin=pin), 201


@teams_bp.route("/api/teams/<int:team_pk>", methods=["PUT", "DELETE"])
@admin_required
def update_or_delete_team(team_pk):
    team = db.session.get(Team, team_pk)
    if not team:
        return jsonify(error="Team not found."), 404
    if request.method == "DELETE":
        if FinalResult.query.filter_by(team_id=team.id).first():
            return jsonify(error="Teams included in generated results cannot be deleted."), 409
        audit("Team deleted", team.team_id)
        db.session.delete(team)
        db.session.commit()
        emit_leaderboard()
        return jsonify(ok=True)
    data = request.get_json(silent=True) or {}
    if any(result.locked for result in FinalResult.query.filter_by(team_id=team.id).all()):
        return jsonify(error="A team in locked results cannot be edited."), 409
    if "team_name" in data:
        name = str(data["team_name"]).strip()
        if not name or len(name) > 120:
            return jsonify(error="Team name is required (120 characters maximum)."), 400
        team.team_name = name
    for field in ("member_1", "member_2", "member_3"):
        if field in data:
            setattr(team, field, str(data[field]).strip()[:100])
    team.members = [
        TeamMember(name=value, position=position)
        for position, value in enumerate((team.member_1, team.member_2, team.member_3), start=1)
        if value
    ]
    if "status" in data:
        status = str(data["status"]).upper()
        if status not in TEAM_STATUSES:
            return jsonify(error="Invalid team status."), 400
        team.status = status
    audit("Team edited", team.team_id)
    db.session.commit()
    emit_leaderboard()
    return jsonify(team=_team_payload(team))


@teams_bp.post("/api/teams/<int:team_pk>/reset-pin")
@admin_required
def reset_pin(team_pk):
    team = db.session.get(Team, team_pk)
    if not team:
        return jsonify(error="Team not found."), 404
    pin = new_team_pin()
    team.set_pin(pin)
    audit("Team PIN reset", team.team_id)
    db.session.commit()
    return jsonify(team_id=team.team_id, login_pin=pin)


@teams_bp.get("/api/teams/<int:team_pk>/timeline")
@admin_required
def team_timeline(team_pk):
    team = db.session.get(Team, team_pk)
    if not team:
        return jsonify(error="Team not found."), 404
    events = []
    for session in RoundSession.query.filter_by(team_id=team.id).all():
        events.append({"at": session.started_at, "label": f"Round {session.round.number} started"})
        if session.ended_at:
            events.append({"at": session.ended_at, "label": f"Round {session.round.number} completed"})
    for scan in ScanLog.query.filter_by(team_id=team.id).all():
        events.append({"at": scan.scan_time, "label": f"{scan.challenge.qr_id} scanned"})
        if scan.answer_time:
            events.append({"at": scan.answer_time, "label": f"{scan.answer_status.title()} answer · {scan.points} pts"})
    for answer in Answer.query.filter_by(team_id=team.id).all():
        if answer.answer_time:
            events.append({"at": answer.answer_time, "label": f"Round {answer.question.round.number} quiz answer · {answer.points} pts"})
    events.sort(key=lambda event: event["at"])
    return jsonify(team=_team_payload(team), timeline=[
        {"at": (event["at"].replace(tzinfo=timezone.utc) if event["at"].tzinfo is None else event["at"].astimezone(timezone.utc)).isoformat(), "label": event["label"]}
        for event in events
    ])


@teams_bp.get("/api/team/dashboard")
@team_required
def team_summary():
    team = current_user
    now = utcnow()
    expired = False
    pending_answers = Answer.query.filter_by(team_id=team.id, answer_time=None).all()
    for attempt in pending_answers:
        started = attempt.question_start_time
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        if (now - started).total_seconds() >= attempt.question.time_limit:
            attempt.answer_time = now
            attempt.selected_answer = ""
            attempt.correct = False
            attempt.points = 0
            audit("Quiz answer timed out", team.team_id, {"question_id": attempt.question_id})
            expired = True
    if expired:
        db.session.commit()
    active_round = Round.query.filter_by(status="ACTIVE").first()
    score = db.session.query(func.coalesce(func.sum(Score.points), 0)).filter_by(team_id=team.id).scalar()
    session = RoundSession.query.filter_by(team_id=team.id, status="ACTIVE").first()
    return jsonify(
        team=_team_payload(team),
        current_round=active_round.name if active_round else "Waiting for round",
        round_id=active_round.id if active_round else None,
        round_number=active_round.number if active_round else None,
        round_status=active_round.status if active_round else "LOCKED",
        score=int(score or 0),
        round_started_at=iso_utc(session.started_at) if session else None,
        session_active=bool(session),
    )


@teams_bp.get("/api/team/rounds")
@team_required
def team_rounds():
    return jsonify([
        {"number": event_round.number, "name": event_round.name, "status": event_round.status}
        for event_round in Round.query.order_by(Round.number)
    ])


@teams_bp.post("/api/team/rounds/<int:round_id>/start")
@team_required
def start_team_round(round_id):
    event_round = db.session.get(Round, round_id)
    if not event_round or event_round.status != "ACTIVE":
        return jsonify(error="This round is not active."), 409
    team = current_user
    if event_round.number > 1:
        previous_round = Round.query.filter_by(number=event_round.number - 1).first()
        previous_session = RoundSession.query.filter_by(
            team_id=team.id,
            round_id=previous_round.id if previous_round else None,
            status="COMPLETED",
        ).first()
        if not previous_session:
            return jsonify(error="Complete the previous round before starting this one."), 409
    session = RoundSession.query.filter_by(team_id=team.id, round_id=round_id).first()
    if not session:
        session = RoundSession(team_id=team.id, round_id=round_id)
        db.session.add(session)
    elif session.status == "COMPLETED":
        return jsonify(error="This team already completed the round."), 409
    else:
        session.status = "ACTIVE"
    team.status = "ACTIVE"
    audit("Team round started", team.team_id, {"round": event_round.number})
    db.session.commit()
    emit_activity(f"{team.team_id} started Round {event_round.number}", "round")
    return jsonify(started_at=iso_utc(session.started_at))
