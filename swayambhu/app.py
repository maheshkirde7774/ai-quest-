from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"))

import click
from flask import Flask, jsonify
from flask_login import current_user
from flask_socketio import join_room

from config import Config
from extensions import csrf, db, login_manager, migrate, socketio
from models import Admin, Round, Team


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)
    Config.validate_runtime()

    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    socketio.init_app(app)
    login_manager.login_view = "auth.admin_login"

    @login_manager.user_loader
    def load_user(identity):
        if not identity or ":" not in identity:
            return None
        kind, record_id = identity.split(":", 1)
        model = Admin if kind == "admin" else Team if kind == "team" else None
        return db.session.get(model, int(record_id)) if model else None

    @login_manager.unauthorized_handler
    def unauthorized():
        from flask import redirect, request, url_for

        endpoint = "auth.team_login" if request.path.startswith("/team") else "auth.admin_login"
        return redirect(url_for(endpoint))

    @socketio.on("join_admin")
    def join_admin_room():
        if current_user.is_authenticated and getattr(current_user, "role", "") in (
            "admin", "super-admin"
        ):
            join_room("admins")

    @socketio.on("join_participant")
    def join_participant_room():
        if current_user.is_authenticated and getattr(current_user, "role", "") in (
            "team", "admin", "super-admin"
        ):
            join_room("participants")

    from routes import register_routes

    register_routes(app)

    @app.get("/health/db")
    def database_health():
        """Check database connectivity without exposing connection details."""
        from sqlalchemy import text

        db.session.execute(text("SELECT 1"))
        return jsonify(status="ok", database=db.engine.dialect.name)

    @app.cli.command("create-admin")
    @click.option("--username", prompt=True)
    @click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
    def create_admin(username, password):
        """Create an administrator without placing credentials in the frontend."""
        if len(password) < 12:
            raise click.ClickException("Use an admin password of at least 12 characters.")
        with app.app_context():
            if Admin.query.filter_by(username=username).first():
                raise click.ClickException("That username already exists.")
            admin = Admin(username=username, role="super-admin")
            admin.set_password(password)
            db.session.add(admin)
            db.session.commit()
            click.echo(f"Administrator {username} created.")

    @app.cli.command("init-db")
    def init_db():
        """Create tables and seed the three event rounds."""
        initialize_database(app)
        click.echo("Database initialized; rounds 1-3 are ready/locked.")

    if app.config.get("AUTO_INIT_DB", True):
        initialize_database(app)
    return app


def initialize_database(app):
    with app.app_context():
        db.create_all()
        rounds = [
            (1, "QR Riddle", "READY"),
            (2, "Quiz Challenge", "LOCKED"),
            (3, "Pen & Paper Final Challenge", "LOCKED"),
        ]
        for number, name, status in rounds:
            if not Round.query.filter_by(number=number).first():
                db.session.add(Round(number=number, name=name, status=status))
        db.session.commit()


app = create_app({"AUTO_INIT_DB": False})


if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000, debug=False)