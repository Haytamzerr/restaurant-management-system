import pytest

from app import create_app
from app.db import get_db, init_db


@pytest.fixture
def app(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "test.sqlite"), "SECRET_KEY": "test"})
    with app.app_context():
        init_db(demo=True)
    return app


@pytest.fixture
def db(app):
    with app.app_context():
        yield get_db()


@pytest.fixture
def client(app):
    return app.test_client()


def csrf_of(client):
    """The form token the pages put in every form."""
    client.get("/login")
    with client.session_transaction() as session:
        return session["csrf"]


@pytest.fixture
def staff(client):
    token = csrf_of(client)
    client.post("/login", data={"username": "admin", "password": "admin", "csrf": token})
    client.token = token
    return client
