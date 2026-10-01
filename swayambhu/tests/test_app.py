import unittest
from datetime import timedelta

from app import create_app
from extensions import db
from models import Event, Answer, Admin, FinalResult, QRChallenge, Round, RoundSession, Score, Team, TeamMember, utcnow
from utils.scoring import leaderboard_rows


class EventAppTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "AUTO_INIT_DB": False,
            "WTF_CSRF_ENABLED": False,
            "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
            "SECRET_KEY": "test-secret-key-long-enough-for-session-signing",
        })
        with self.app.app_context():
            db.create_all()
            db.session.add(Event(id=1, active=False))
            db.session.add_all([
                Round(number=1, name="QR Riddle", status="READY"),
                Round(number=2, name="Quiz Challenge", status="LOCKED"),
                Round(number=3, name="Pen & Paper Final Challenge", status="LOCKED"),
            ])
            admin = Admin(username="operator", role="super-admin")
            admin.set_password("a-secure-test-password")
            db.session.add(admin)
            db.session.commit()
        self.client = self.app.test_client()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all();db.engine.dispose()

    def login_admin(self):
        return self.client.post("/admin/login", data={
            "username": "operator", "password": "a-secure-test-password"
        })

    def create_team(self):
        response = self.client.post("/api/teams", json={"team_name": "Test Team", "member_1": "Alex"})
        self.assertEqual(response.status_code, 201)
        return response.get_json()

    def test_protected_admin_and_team_boundary(self):
        self.assertEqual(self.client.get("/api/overview").status_code, 403)
        self.login_admin()
        created = self.create_team()
        team_client = self.app.test_client()
        team_client.post("/team/login", data={
            "team_id": created["team"]["team_id"], "pin": created["login_pin"]
        })
        self.assertEqual(self.client.get("/api/admin/profile").status_code, 200)
        self.assertEqual(team_client.get("/api/overview").status_code, 403)
        self.assertEqual(team_client.get("/api/team/dashboard").status_code, 200)

    def test_database_health_and_team_member_records(self):
        self.login_admin()
        response = self.client.get("/health/db")
        self.assertEqual(response.get_json(), {"database": "sqlite", "status": "ok"})
        created = self.client.post("/api/teams", json={
            "team_name": "Members Team", "member_1": "Alex", "member_2": "Sam"
        })
        self.assertEqual(created.status_code, 201)
        with self.app.app_context():
            team = Team.query.filter_by(team_name="Members Team").one()
            self.assertEqual([member.name for member in team.members], ["Alex", "Sam"])
            self.assertEqual(TeamMember.query.filter_by(team_id=team.id).count(), 2)

    def test_final_result_tiebreaks_by_duration_then_completion(self):
        with self.app.app_context():
            started_at = utcnow()
            teams = []
            for team_id, name in (
                ("AIQ-001", "Slow"),
                ("AIQ-002", "Fast, later"),
                ("AIQ-003", "Fast, earlier"),
            ):
                team = Team(team_id=team_id, team_name=name, status="COMPLETED")
                team.set_pin("123456")
                db.session.add(team)
                teams.append(team)
            db.session.flush()
            for event_round in Round.query.order_by(Round.number):
                event_round.status = "ENDED"
            durations = [(120, 120), (60, 120), (60, 90)]
            for team, (duration, completion) in zip(teams, durations):
                db.session.add(Score(team_id=team.id, round_id=1, points=50))
                db.session.add(Score(team_id=team.id, round_id=3, points=10))
                for round_number in (1, 2, 3):
                    round_duration = duration if round_number == 1 else 10
                    db.session.add(RoundSession(
                        team_id=team.id,
                        round_id=round_number,
                        status="COMPLETED",
                        started_at=started_at + timedelta(seconds=completion - round_duration),
                        ended_at=started_at + timedelta(seconds=completion),
                    ))
            db.session.commit()

        self.login_admin()
        generated = self.client.post("/api/results/generate", json={})
        self.assertEqual(generated.status_code, 201, generated.get_data(as_text=True))
        results = self.client.get("/api/results").get_json()
        self.assertEqual([row["team_id"] for row in results], ["AIQ-003", "AIQ-002", "AIQ-001"])
        self.assertEqual(self.client.post("/api/results/lock", json={}).status_code, 200)
        self.assertEqual(self.client.post("/api/results/generate", json={}).status_code, 409)
        with self.app.app_context():
            self.assertEqual(FinalResult.query.filter_by(locked=True).count(), 3)

    def test_leaderboard_tiebreak_uses_completion_time(self):
        with self.app.app_context():
            base = utcnow()
            team_1 = Team(team_id="AIQ-010", team_name="Later Finish", status="ACTIVE")
            team_1.set_pin("123456")
            team_2 = Team(team_id="AIQ-011", team_name="Earlier Finish", status="ACTIVE")
            team_2.set_pin("123456")
            db.session.add_all([team_1, team_2])
            db.session.flush()
            db.session.add_all([
                Score(team_id=team_1.id, round_id=1, points=50),
                Score(team_id=team_1.id, round_id=2, points=30),
                Score(team_id=team_2.id, round_id=1, points=50),
                Score(team_id=team_2.id, round_id=2, points=30),
                RoundSession(team_id=team_1.id, round_id=1, status="COMPLETED", started_at=base, ended_at=base + timedelta(seconds=120)),
                RoundSession(team_id=team_1.id, round_id=2, status="COMPLETED", started_at=base + timedelta(seconds=200), ended_at=base + timedelta(seconds=380)),
                RoundSession(team_id=team_2.id, round_id=1, status="COMPLETED", started_at=base + timedelta(seconds=10), ended_at=base + timedelta(seconds=130)),
                RoundSession(team_id=team_2.id, round_id=2, status="COMPLETED", started_at=base + timedelta(seconds=170), ended_at=base + timedelta(seconds=350)),
            ])
            db.session.commit()
        with self.app.app_context():
            rows = leaderboard_rows()
        self.assertEqual([row["team_id"] for row in rows], ["AIQ-011", "AIQ-010"])
        self.assertEqual(rows[0]["rank"], 1)
        self.assertEqual(rows[1]["rank"], 2)
        self.assertEqual(rows[0]["time"], 300)

    def test_team_cannot_skip_a_round(self):
        self.login_admin()
        created = self.create_team()
        with self.app.app_context():
            Round.query.filter_by(number=2).first().status = "ACTIVE"
            db.session.commit()
        team_client = self.app.test_client()
        team_client.post("/team/login", data={
            "team_id": created["team"]["team_id"], "pin": created["login_pin"]
        })
        self.assertEqual(team_client.post("/api/team/rounds/2/start", json={}).status_code, 409)

    def test_ending_round_unlocks_the_next_round(self):
        self.login_admin()
        self.assertEqual(self.client.post("/api/rounds/1/start", json={}).status_code, 200)
        self.assertEqual(self.client.post("/api/rounds/1/end", json={}).status_code, 200)
        with self.app.app_context():
            self.assertEqual(Round.query.filter_by(number=2).one().status, "READY")


if __name__ == "__main__":
    unittest.main()