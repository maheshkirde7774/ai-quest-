from datetime import datetime, timedelta, timezone

from flask import Blueprint, jsonify, request, send_file
from flask_login import current_user
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from extensions import db
from models import Answer, Question, QRChallenge, Round, RoundSession, ScanLog, Score, Team, utcnow
from routes.common import admin_required, audit, emit_activity, emit_leaderboard, iso_utc, team_required
from utils.qr_generator import render_qr
from utils.security import new_qr_token

qr_bp = Blueprint("qr", __name__)


def _qr_payload(challenge):
    return {
        "id": challenge.id,
        "qr_id": challenge.qr_id,
        "round_id": challenge.round_id,
        "round": challenge.round.number,
        "round_name": challenge.round.name,
        "question_id": challenge.question_id,
        "room": challenge.room,
        "status": challenge.status,
        "created_at": iso_utc(challenge.created_at),
        "activated_at": iso_utc(challenge.activated_at),
        "expires_at": iso_utc(challenge.expires_at),
        "scans": len(challenge.scans),
    }


def _add_points(team_id, round_id, points):
    row = Score.query.filter_by(team_id=team_id, round_id=round_id).first()
    if not row:
        row = Score(team_id=team_id, round_id=round_id, points=0)
        db.session.add(row)
    row.points += points
    row.updated_at = utcnow()


@qr_bp.get("/api/qrs")
@admin_required
def list_qrs():
    return jsonify([_qr_payload(qr) for qr in QRChallenge.query.order_by(QRChallenge.id.desc())])


@qr_bp.post("/api/qrs")
@admin_required
def create_qr():
    data = request.get_json(silent=True) or {}
    event_round = db.session.get(Round, data.get("round_id"))
    if not event_round:
        return jsonify(error="Select a valid round."), 400
    room = str(data.get("room", "")).strip()
    if len(room) > 120:
        return jsonify(error="Room must be 120 characters or fewer."), 400
    question = None
    if data.get("question_id"):
        question = db.session.get(Question, data["question_id"])
        if not question or question.round_id != event_round.id:
            return jsonify(error="The clue must belong to the selected round."), 400
    expires_at = None
    if data.get("expires_at"):
        try:
            expires_at = datetime.fromisoformat(str(data["expires_at"]).replace("Z", "+00:00"))
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
        except ValueError:
            return jsonify(error="Expiration must be a valid date and time."), 400
    prefix = f"QR-R{event_round.number}-"
    numbers = [
        int(challenge.qr_id.rsplit("-", 1)[1])
        for challenge in QRChallenge.query.filter_by(round_id=event_round.id).all()
        if challenge.qr_id.startswith(prefix)
    ]
    number = max(numbers, default=0) + 1
    challenge = QRChallenge(
        qr_id=f"QR-R{event_round.number}-{number:03d}",
        secure_token=new_qr_token(),
        round_id=event_round.id,
        question_id=question.id if question else None,
        room=room,
        expires_at=expires_at,
    )
    db.session.add(challenge)
    audit("QR generated", challenge.qr_id, {"round": event_round.number})
    db.session.commit()
    return jsonify(qr=_qr_payload(challenge)), 201


@qr_bp.get("/api/qrs/<int:qr_pk>/image")
@admin_required
def qr_image(qr_pk):
    challenge = db.session.get(QRChallenge, qr_pk)
    if not challenge:
        return jsonify(error="QR not found."), 404
    payload = request.host_url.rstrip("/") + "/scan/" + challenge.secure_token
    return send_file(render_qr(payload), mimetype="image/png", download_name=f"{challenge.qr_id}.png")


@qr_bp.post("/api/qrs/<int:qr_pk>/<action>")
@admin_required
def manage_qr(qr_pk, action):
    challenge = db.session.get(QRChallenge, qr_pk)
    if not challenge:
        return jsonify(error="QR not found."), 404
    if action == "activate":
        if challenge.round.status not in ("READY", "ACTIVE"):
            return jsonify(error="Unlock the QR's round before activation."), 409
        challenge.status = "ACTIVE"
        challenge.activated_at = utcnow()
        challenge.deactivated_at = None
        audit("QR activated", challenge.qr_id)
    elif action == "deactivate":
        challenge.status = "INACTIVE"
        challenge.deactivated_at = utcnow()
        audit("QR deactivated", challenge.qr_id)
    elif action == "delete":
        if challenge.scans:
            return jsonify(error="A QR with recorded scans cannot be deleted."), 409
        audit("QR deleted", challenge.qr_id)
        db.session.delete(challenge)
        db.session.commit()
        return jsonify(ok=True)
    else:
        return jsonify(error="Unknown QR action."), 404
    db.session.commit()
    emit_activity(f"{challenge.qr_id} {action}d", "qr")
    return jsonify(qr=_qr_payload(challenge))


@qr_bp.get("/api/qrs/<int:qr_pk>/scans")
@admin_required
def qr_scans(qr_pk):
    challenge = db.session.get(QRChallenge, qr_pk)
    if not challenge:
        return jsonify(error="QR not found."), 404
    return jsonify([
        {"team_id": scan.team.team_id, "team_name": scan.team.team_name,
         "scan_time": iso_utc(scan.scan_time), "answer_time": iso_utc(scan.answer_time),
         "answer_status": scan.answer_status, "points": scan.points}
        for scan in ScanLog.query.filter_by(qr_id=challenge.id).order_by(ScanLog.scan_time.desc())
    ])


@qr_bp.post("/api/team/scan")
@team_required
def scan_qr():
    data = request.get_json(silent=True) or {}
    token = str(data.get("token", ""))
    challenge = QRChallenge.query.filter_by(secure_token=token).first()
    if not challenge:
        return jsonify(error="This QR code is not recognized."), 404
    if challenge.status != "ACTIVE":
        return jsonify(error="This QR challenge is not active."), 409
    expiration = challenge.expires_at
    if expiration and expiration.tzinfo is None:
        expiration = expiration.replace(tzinfo=timezone.utc)
    if expiration and utcnow() > expiration:
        return jsonify(error="This QR challenge has expired."), 410
    if challenge.round.status != "ACTIVE":
        return jsonify(error="This QR belongs to a round that is not active."), 409
    if RoundSession.query.filter_by(team_id=current_user.id, round_id=challenge.round_id, status="ACTIVE").first() is None:
        return jsonify(error="Start this round from your dashboard before scanning."), 409
    if ScanLog.query.filter_by(team_id=current_user.id, qr_id=challenge.id).first():
        return jsonify(error="Your team already scanned this QR."), 409
    scan = ScanLog(
        team_id=current_user.id,
        qr_id=challenge.id,
        round_id=challenge.round_id,
        scan_time=utcnow(),
    )
    db.session.add(scan)
    audit("QR scanned", f"{current_user.team_id} · {challenge.qr_id}", {"scan_time": scan.scan_time.isoformat()})
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return jsonify(error="Your team already scanned this QR."), 409
    emit_activity(f"{current_user.team_id} scanned {challenge.qr_id}", "scan")
    emit_leaderboard()
    question = challenge.question
    return jsonify(
        scan_id=scan.id,
        qr_id=challenge.qr_id,
        prompt=question.prompt if question else "QR scanned. Check with the event marshal for your clue.",
        requires_answer=bool(question),
    )


@qr_bp.post("/api/team/scan/<int:scan_id>/answer")
@team_required
def submit_qr_answer(scan_id):
    scan = db.session.get(ScanLog, scan_id)
    if not scan or scan.team_id != current_user.id:
        return jsonify(error="Scan not found."), 404
    if scan.answer_time:
        return jsonify(error="An answer has already been recorded for this scan."), 409
    if scan.challenge.round.status != "ACTIVE":
        return jsonify(error="This challenge's round is no longer active."), 409
    if not RoundSession.query.filter_by(team_id=current_user.id, round_id=scan.round_id, status="ACTIVE").first():
        return jsonify(error="Your round session is no longer active."), 409
    data = request.get_json(silent=True) or {}
    answer = str(data.get("answer", "")).strip()
    if not answer or len(answer) > 500:
        return jsonify(error="Enter an answer of 1 to 500 characters."), 400
    question = scan.challenge.question
    correct = bool(question) and answer.casefold() == question.correct_answer.strip().casefold()
    scan.answer_time = utcnow()
    scan.submitted_answer = answer
    scan.answer_status = "CORRECT" if correct else "INCORRECT"
    scan.points = question.points if correct else 0
    if correct:
        _add_points(current_user.id, scan.round_id, scan.points)
    audit("QR answer submitted", f"{current_user.team_id} · {scan.challenge.qr_id}", {"status": scan.answer_status, "points": scan.points})
    db.session.commit()
    emit_activity(f"{current_user.team_id} answered {scan.challenge.qr_id}: {scan.answer_status.lower()}", "answer")
    emit_leaderboard()
    return jsonify(correct=correct, points=scan.points)


@qr_bp.post("/api/team/quiz/next")
@team_required
def next_quiz_question():
    active_round = Round.query.filter_by(status="ACTIVE", number=2).first()
    if not active_round:
        return jsonify(error="The quiz round is not active."), 409
    session = RoundSession.query.filter_by(team_id=current_user.id, round_id=active_round.id, status="ACTIVE").first()
    if not session:
        return jsonify(error="Start Round 2 from your dashboard first."), 409
    outstanding = Answer.query.filter_by(team_id=current_user.id, round_id=active_round.id, answer_time=None).first()
    if outstanding:
        question_started = outstanding.question_start_time
        if question_started.tzinfo is None:
            question_started = question_started.replace(tzinfo=timezone.utc)
        if (utcnow() - question_started).total_seconds() >= outstanding.question.time_limit:
            outstanding.answer_time = utcnow()
            outstanding.selected_answer = ""
            outstanding.correct = False
            outstanding.points = 0
            db.session.commit()
            outstanding = None
    if outstanding:
        question = outstanding.question
    else:
        answered = select(Answer.question_id).where(
            Answer.team_id == current_user.id,
            Answer.round_id == active_round.id,
        )
        question = Question.query.filter_by(round_id=active_round.id, active=True).filter(
            ~Question.id.in_(answered)
        ).order_by(Question.id).first()
        if not question:
            return jsonify(done=True, message="No more quiz questions."), 200
        outstanding = Answer(
            team_id=current_user.id,
            question_id=question.id,
            round_id=active_round.id,
            question_start_time=utcnow(),
        )
        db.session.add(outstanding)
        db.session.commit()
    return jsonify(
        answer_id=outstanding.id,
        question_id=question.id,
        question=question.prompt,
        options={"A": question.option_a, "B": question.option_b, "C": question.option_c, "D": question.option_d},
        points=question.points,
        time_limit=question.time_limit,
        started_at=iso_utc(outstanding.question_start_time),
    )


@qr_bp.post("/api/team/quiz/<int:answer_id>/submit")
@team_required
def submit_quiz_answer(answer_id):
    attempt = db.session.get(Answer, answer_id)
    if not attempt or attempt.team_id != current_user.id:
        return jsonify(error="Quiz attempt not found."), 404
    if attempt.answer_time:
        return jsonify(error="This question has already been submitted."), 409
    if attempt.question.round.status != "ACTIVE" or not RoundSession.query.filter_by(
        team_id=current_user.id, round_id=attempt.round_id, status="ACTIVE"
    ).first():
        return jsonify(error="Your quiz round is no longer active."), 409
    data = request.get_json(silent=True) or {}
    selected = str(data.get("selected_answer", "")).upper()
    if selected not in {"A", "B", "C", "D", ""}:
        return jsonify(error="Choose one of the available answers."), 400
    attempt.answer_time = utcnow()
    question_started = attempt.question_start_time
    answer_recorded = attempt.answer_time
    if question_started.tzinfo is None:
        question_started = question_started.replace(tzinfo=timezone.utc)
    if answer_recorded.tzinfo is None:
        answer_recorded = answer_recorded.replace(tzinfo=timezone.utc)
    within_time = (answer_recorded - question_started).total_seconds() <= attempt.question.time_limit
    attempt.selected_answer = selected if within_time else ""
    attempt.correct = within_time and selected == attempt.question.correct_answer.upper()
    attempt.points = attempt.question.points if attempt.correct else 0
    if attempt.correct:
        _add_points(current_user.id, attempt.round_id, attempt.points)
    audit("Quiz answer submitted", current_user.team_id, {"question_id": attempt.question_id, "correct": attempt.correct, "points": attempt.points})
    db.session.commit()
    emit_leaderboard()
    return jsonify(correct=attempt.correct, points=attempt.points, expired=not within_time)


@qr_bp.post("/api/admin/questions")
@admin_required
def add_question():
    data = request.get_json(silent=True) or {}
    event_round = db.session.get(Round, data.get("round_id"))
    prompt = str(data.get("prompt", "")).strip()
    answer = str(data.get("correct_answer", "")).strip()
    if not event_round or not prompt or len(prompt) > 2000:
        return jsonify(error="Select a round and enter a question (2,000 characters maximum)."), 400
    if not answer or len(answer) > 300:
        return jsonify(error="Enter a correct answer of 1 to 300 characters."), 400
    if event_round.number == 2 and answer.upper() not in {"A", "B", "C", "D"}:
        return jsonify(error="Quiz correct answer must be A, B, C, or D."), 400
    try:
        points = int(data.get("points", 10))
        time_limit = int(data.get("time_limit", 60))
    except (TypeError, ValueError):
        return jsonify(error="Points and time limit must be whole numbers."), 400
    if not 0 <= points <= 10000 or not 5 <= time_limit <= 3600:
        return jsonify(error="Points must be 0-10,000 and time limit 5-3,600 seconds."), 400
    question = Question(
        round_id=event_round.id,
        prompt=prompt,
        option_a=str(data.get("option_a", ""))[:300],
        option_b=str(data.get("option_b", ""))[:300],
        option_c=str(data.get("option_c", ""))[:300],
        option_d=str(data.get("option_d", ""))[:300],
        correct_answer=answer.upper() if event_round.number == 2 else answer,
        points=points,
        time_limit=time_limit,
    )
    db.session.add(question)
    audit("Question created", f"Round {event_round.number}")
    db.session.commit()
    return jsonify(id=question.id), 201


@qr_bp.get("/api/admin/questions")
@admin_required
def list_questions():
    return jsonify([
        {"id": q.id, "round_id": q.round_id, "round": q.round.number, "prompt": q.prompt,
         "options": [q.option_a, q.option_b, q.option_c, q.option_d],
         "option_a": q.option_a, "option_b": q.option_b, "option_c": q.option_c,
         "option_d": q.option_d, "correct_answer": q.correct_answer, "points": q.points,
         "time_limit": q.time_limit, "active": q.active}
        for q in Question.query.order_by(Question.round_id, Question.id)
    ])


@qr_bp.route("/api/admin/questions/<int:question_id>", methods=["PATCH", "DELETE"])
@admin_required
def edit_question(question_id):
    question = db.session.get(Question, question_id)
    if not question:
        return jsonify(error="Question not found."), 404
    if request.method == "DELETE":
        if question.answers or QRChallenge.query.filter_by(question_id=question.id).first():
            return jsonify(error="Questions used by attempts or QR challenges cannot be deleted."), 409
        audit("Question deleted", question.id)
        db.session.delete(question)
        db.session.commit()
        return jsonify(ok=True)
    data = request.get_json(silent=True) or {}
    editable = {
        "prompt", "option_a", "option_b", "option_c", "option_d",
        "correct_answer", "points", "time_limit",
    }
    if editable.intersection(data) and (
        Answer.query.filter_by(question_id=question.id).first()
        or QRChallenge.query.filter_by(question_id=question.id).join(ScanLog).first()
    ):
        return jsonify(error="A question with recorded attempts cannot be edited."), 409
    if "prompt" in data:
        prompt = str(data["prompt"]).strip()
        if not prompt or len(prompt) > 2000:
            return jsonify(error="Question is required (2,000 characters maximum)."), 400
        question.prompt = prompt
    for field in ("option_a", "option_b", "option_c", "option_d"):
        if field in data:
            setattr(question, field, str(data[field])[:300])
    if "correct_answer" in data:
        answer = str(data["correct_answer"]).strip()
        if not answer or len(answer) > 300:
            return jsonify(error="Enter a correct answer of 1 to 300 characters."), 400
        if question.round.number == 2 and answer.upper() not in {"A", "B", "C", "D"}:
            return jsonify(error="Quiz correct answer must be A, B, C, or D."), 400
        question.correct_answer = answer.upper() if question.round.number == 2 else answer
    try:
        points = int(data.get("points", question.points))
        time_limit = int(data.get("time_limit", question.time_limit))
    except (TypeError, ValueError):
        return jsonify(error="Points and time limit must be whole numbers."), 400
    if not 0 <= points <= 10000 or not 5 <= time_limit <= 3600:
        return jsonify(error="Points must be 0-10,000 and time limit 5-3,600 seconds."), 400
    question.points = points
    question.time_limit = time_limit
    if "active" in data:
        question.active = bool(data["active"])
    audit("Question updated", question.id, {"active": question.active})
    db.session.commit()
    return jsonify(id=question.id, active=question.active)


@qr_bp.post("/api/admin/round-three/score")
@admin_required
def judge_round_three():
    data = request.get_json(silent=True) or {}
    team = db.session.get(Team, data.get("team_id"))
    event_round = Round.query.filter_by(number=3).first()
    if not team or not event_round:
        return jsonify(error="Team or final round not found."), 404
    if any(result.locked for result in team.final_results):
        return jsonify(error="Final results are locked."), 409
    try:
        points = int(data.get("score"))
    except (TypeError, ValueError):
        return jsonify(error="Enter a whole-number score."), 400
    if not 0 <= points <= 100000:
        return jsonify(error="Score must be between 0 and 100,000."), 400
    session = RoundSession.query.filter_by(team_id=team.id, round_id=event_round.id).first()
    if not session:
        return jsonify(error="The team must start Round 3 before judge evaluation."), 409
    session.ended_at = utcnow()
    session.status = "COMPLETED"
    score = Score.query.filter_by(team_id=team.id, round_id=event_round.id).first()
    if not score:
        score = Score(team_id=team.id, round_id=event_round.id)
        db.session.add(score)
    score.points = points
    team.status = "COMPLETED"
    audit("Round 3 score entered", team.team_id, {"score": points, "remarks": str(data.get("remarks", ""))[:1000]})
    db.session.commit()
    emit_leaderboard()
    return jsonify(ok=True, score=points)


@qr_bp.get("/api/admin/monitoring")
@admin_required
def monitoring():
    result = []
    for team in Team.query.order_by(Team.team_id):
        latest = ScanLog.query.filter_by(team_id=team.id).order_by(ScanLog.scan_time.desc()).first()
        session = RoundSession.query.filter_by(team_id=team.id, status="ACTIVE").first()
        activity_times = [
            value for value in [
                latest.scan_time if latest else None,
                session.ended_at if session else None,
                session.started_at if session else None,
            ] if value
        ]
        last_activity = max(activity_times, default=None)
        result.append({
            **{"team_id": team.team_id, "team_name": team.team_name, "status": team.status},
            "round": session.round.number if session else (latest.challenge.round.number if latest else 0),
            "current_qr": latest.challenge.qr_id if latest else "-",
            "last_scan": iso_utc(latest.scan_time) if latest else None,
            "score": sum(row.points for row in team.scores),
            "round_start": iso_utc(session.started_at) if session else None,
            "last_activity": iso_utc(last_activity),
        })
    return jsonify(result)
