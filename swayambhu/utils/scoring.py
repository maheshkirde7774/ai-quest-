from sqlalchemy import func

from extensions import db
from models import Score, Team


def refresh_round_score(team_id, round_id):
    round_points = db.session.query(func.coalesce(func.sum(Score.points), 0)).filter_by(
        team_id=team_id, round_id=round_id
    ).scalar()
    return int(round_points or 0)


def leaderboard_rows():
    teams = db.session.query(Team).filter(
        Team.status.notin_(("DISQUALIFIED", "DISABLED"))
    ).all()
    return sorted(
        [
            {
                "team_id": team.team_id,
                "team_name": team.team_name,
                "score": sum(score.points for score in team.scores),
                "time": sum(
                    int((session.ended_at - session.started_at).total_seconds())
                    for session in team.round_sessions
                    if session.ended_at
                ),
                "status": team.status,
                "round": max((s.round.number for s in team.round_sessions), default=0),
            }
            for team in teams
        ],
        key=lambda row: (-row["score"], row["time"], row["team_id"]),
    )
