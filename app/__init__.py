"""Restaurant Management System: menu, stock, orders and sales for a small restaurant."""

import os
import secrets
from pathlib import Path

from flask import Flask, abort, request, session

from app import db
from app.services import money


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-change-me"),
        DATABASE=str(Path(app.instance_path) / "restaurant.sqlite"),
    )
    if test_config:
        app.config.update(test_config)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    app.teardown_appcontext(db.close_db)
    app.cli.add_command(db.init_db_command)
    app.jinja_env.filters["money"] = money

    @app.before_request
    def create_database_on_first_run():
        if not Path(app.config["DATABASE"]).exists():
            db.init_db(demo=True)

    # CSRF protection: every form carries a token tied to the session
    @app.before_request
    def check_csrf():
        if request.method == "POST" and not app.config.get("TESTING_NO_CSRF"):
            token = session.get("csrf")
            if not token or request.form.get("csrf") != token:
                abort(400, "invalid form token, reload the page")

    @app.context_processor
    def csrf_token():
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(16)
        return {"csrf": session["csrf"]}

    from app import auth, public, staff

    app.register_blueprint(auth.bp)
    app.register_blueprint(public.bp)
    app.register_blueprint(staff.bp)
    return app
