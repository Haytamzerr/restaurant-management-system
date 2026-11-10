"""Staff login. Passwords are stored hashed (werkzeug, scrypt), never in clear."""

import functools

from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from app.db import get_db

bp = Blueprint("auth", __name__)


@bp.before_app_request
def load_user():
    user_id = session.get("user_id")
    g.user = get_db().execute("SELECT id, username FROM users WHERE id = ?", (user_id,)).fetchone() if user_id else None


def login_required(view):
    @functools.wraps(view)
    def wrapped(**kwargs):
        if g.user is None:
            return redirect(url_for("auth.login", next=request.path))
        return view(**kwargs)

    return wrapped


@bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = get_db().execute(
            "SELECT * FROM users WHERE username = ?", (request.form.get("username", ""),)
        ).fetchone()
        if user and check_password_hash(user["password_hash"], request.form.get("password", "")):
            csrf = session.get("csrf")
            session.clear()  # a new session on login (prevents session fixation)
            session["user_id"], session["csrf"] = user["id"], csrf
            target = request.args.get("next", "")
            return redirect(target if target.startswith("/") and not target.startswith("//") else url_for("staff.dashboard"))
        flash("Wrong username or password", "error")
    return render_template("login.html")


@bp.route("/logout", methods=["POST"])
def logout():
    session.pop("user_id", None)
    return redirect(url_for("public.welcome"))


@bp.route("/password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        new = request.form.get("new", "")
        user = get_db().execute("SELECT * FROM users WHERE id = ?", (g.user["id"],)).fetchone()
        if not check_password_hash(user["password_hash"], request.form.get("current", "")):
            flash("Current password is wrong", "error")
        elif len(new) < 8:
            flash("The new password needs at least 8 characters", "error")
        else:
            get_db().execute("UPDATE users SET password_hash = ? WHERE id = ?",
                             (generate_password_hash(new), g.user["id"]))  # fmt: skip
            flash("Password changed", "ok")
            return redirect(url_for("staff.dashboard"))
    return render_template("staff/password.html")
