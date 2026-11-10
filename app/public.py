"""What customers see: the welcome page and the menu with its filters."""

from flask import Blueprint, render_template, request

from app import services
from app.db import get_db

bp = Blueprint("public", __name__)

ALLERGENS = ["gluten", "milk", "eggs", "fish", "shellfish", "nuts", "peanuts", "soy", "sesame"]


@bp.route("/")
def welcome():
    return render_template("welcome.html")


@bp.route("/menu")
def menu():
    db = get_db()
    filters = {
        "category": request.args.get("category", type=int),
        "vegetarian": request.args.get("vegetarian") == "1",
        "gluten_free": request.args.get("gluten_free") == "1",
        "without": request.args.get("without", ""),
    }
    dishes = services.menu(db, **filters)
    categories = db.execute("SELECT * FROM categories ORDER BY position").fetchall()
    return render_template("menu.html", dishes=dishes, categories=categories, filters=filters,
                           allergens=ALLERGENS)  # fmt: skip
