"""The web pages, called like a browser would."""

from tests.conftest import csrf_of


def test_public_pages(client):
    assert b"Welcome" in client.get("/").data
    page = client.get("/menu?vegetarian=1").data.decode()
    assert "Garden salad" in page and "Cheeseburger" not in page
    assert "Sold out today" in client.get("/menu").data.decode()  # panna cotta, no cream left


def test_staff_pages_need_login(client):
    response = client.get("/staff/orders")
    assert response.status_code == 302 and "/login" in response.headers["Location"]


def test_wrong_password_is_refused(client):
    token = csrf_of(client)
    page = client.post("/login", data={"username": "admin", "password": "nope", "csrf": token})
    assert b"Wrong username or password" in page.data


def test_forms_without_token_are_rejected(staff):
    assert staff.post("/staff/customers", data={"name": "X"}).status_code == 400


def test_take_an_order_from_the_form(staff):
    page = staff.post("/staff/orders/new", data={"csrf": staff.token, "table_no": "3", "dish_1": "2"},
                      follow_redirects=True).data.decode()  # fmt: skip
    assert "sent to the kitchen" in page
    assert "2 × Pasta bolognese" in staff.get("/staff/orders").data.decode()


def test_out_of_stock_order_shows_why(staff):
    page = staff.post("/staff/orders/new", data={"csrf": staff.token, "dish_10": "5"},
                      follow_redirects=True).data.decode()  # fmt: skip
    assert "not enough Cream" in page


def test_create_dish_with_recipe(staff):
    data = {"csrf": staff.token, "name": "Harira", "price": "18.5", "category_id": "1",
            "emoji": "🥣", "active": "on", "vegetarian": "on", "allergens": ["gluten"], "ing_7": "150"}  # fmt: skip
    staff.post("/staff/dishes/new", data=data)
    menu = staff.get("/menu").data.decode()
    assert "Harira" in menu and "18.50 MAD" in menu


def test_restock_and_export(staff):
    staff.post("/staff/stock/10", data={"csrf": staff.token, "mode": "add", "amount": "1000"})
    csv = staff.get("/staff/export/stock.csv")
    assert csv.mimetype == "text/csv"
    assert "Seafood,g,1300.0" in csv.data.decode()


def test_change_password(staff):
    staff.post("/password", data={"csrf": staff.token, "current": "admin", "new": "a-better-one"})
    staff.post("/logout", data={"csrf": staff.token})
    token = csrf_of(staff)
    ok = staff.post("/login", data={"username": "admin", "password": "a-better-one", "csrf": token})
    assert ok.status_code == 302
