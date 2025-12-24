import os
import sqlite3
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, flash, session

# ===============================
# إعدادات أساسية
# ===============================

app = Flask(__name__)

# Secret Key (من Render Environment)
app.secret_key = os.environ.get("SECRET_KEY", "fallback_secret_key")

# مسار قاعدة البيانات (ثابت على Render)
DB_PATH = "/data/inventory.db"

ADMIN_USER = "admin"
ADMIN_PASS = "123"


# ===============================
# أدوات مساعدة
# ===============================

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    os.makedirs("/data", exist_ok=True)
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category TEXT,
        model TEXT,
        serial_number TEXT UNIQUE,
        capacity TEXT,
        displacement TEXT,
        color TEXT,
        quantity INTEGER,
        location TEXT,
        type TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS sales (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER,
        quantity_sold INTEGER,
        sale_date TEXT,
        customer_name TEXT,
        customer_phone TEXT,
        salesman TEXT,
        price REAL,
        specs_info TEXT
    )
    """)

    conn.commit()
    conn.close()


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


# ===============================
# Routes
# ===============================

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if (
            request.form["username"] == ADMIN_USER
            and request.form["password"] == ADMIN_PASS
        ):
            session["logged_in"] = True
            return redirect(url_for("index"))
        flash("بيانات الدخول غير صحيحة", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def index():
    product_type = request.args.get("type", "كباس")
    search = request.args.get("search", "")

    conn = get_db()
    if search:
        products = conn.execute("""
        SELECT * FROM products
        WHERE type = ?
        AND (model LIKE ? OR serial_number LIKE ? OR capacity LIKE ?)
        """, (product_type, f"%{search}%", f"%{search}%", f"%{search}%")).fetchall()
    else:
        products = conn.execute(
            "SELECT * FROM products WHERE type = ?",
            (product_type,)
        ).fetchall()

    conn.close()
    return render_template("index.html", products=products, current_type=product_type)


@app.route("/add", methods=["GET", "POST"])
@login_required
def add_product():
    if request.method == "POST":
        data = (
            request.form["category"],
            request.form["model"],
            request.form["serial"],
            request.form["capacity"],
            request.form["displacement"],
            request.form["color"],
            int(request.form["quantity"]),
            request.form["location"],
            request.form["type"]
        )

        conn = get_db()
        try:
            conn.execute("""
            INSERT INTO products
            (category, model, serial_number, capacity, displacement, color, quantity, location, type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, data)
            conn.commit()
        except sqlite3.IntegrityError:
            flash("السيريال موجود بالفعل", "danger")
        finally:
            conn.close()

        return redirect(url_for("index", type=request.form["type"]))

    return render_template("add.html")


@app.route("/sell/<int:pid>", methods=["GET", "POST"])
@login_required
def sell(pid):
    conn = get_db()
    product = conn.execute(
        "SELECT * FROM products WHERE id = ?", (pid,)
    ).fetchone()

    if request.method == "POST":
        qty = int(request.form["qty"])
        if qty > product["quantity"]:
            flash("الكمية غير كافية", "danger")
        else:
            specs = f"قدرة: {product['capacity']} | إزاحة: {product['displacement']} | لون: {product['color']}"

            cur = conn.cursor()
            cur.execute("""
            INSERT INTO sales
            (product_id, quantity_sold, sale_date, customer_name, customer_phone, salesman, price, specs_info)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                pid,
                qty,
                datetime.now().strftime("%Y-%m-%d %H:%M"),
                request.form["name"],
                request.form["phone"],
                request.form["salesman"],
                float(request.form["price"]),
                specs
            ))

            conn.execute(
                "UPDATE products SET quantity = quantity - ? WHERE id = ?",
                (qty, pid)
            )

            conn.commit()
            sale_id = cur.lastrowid
            conn.close()
            return redirect(url_for("invoice", sale_id=sale_id))

    conn.close()
    return render_template("sell.html", product=product)


@app.route("/invoice/<int:sale_id>")
@login_required
def invoice(sale_id):
    conn = get_db()
    sale = conn.execute("""
    SELECT s.*, p.model, p.serial_number, p.type
    FROM sales s
    JOIN products p ON s.product_id = p.id
    WHERE s.id = ?
    """, (sale_id,)).fetchone()
    conn.close()
    return render_template("invoice.html", sale=sale)


@app.route("/sales")
@login_required
def sales():
    conn = get_db()
    sales = conn.execute("""
    SELECT s.*, p.model
    FROM sales s
    JOIN products p ON s.product_id = p.id
    ORDER BY s.id DESC
    """).fetchall()
    conn.close()
    return render_template("sales.html", sales=sales)


@app.route("/return/<int:sale_id>")
@login_required
def return_sale(sale_id):
    conn = get_db()
    sale = conn.execute(
        "SELECT * FROM sales WHERE id = ?", (sale_id,)
    ).fetchone()

    if sale:
        conn.execute(
            "UPDATE products SET quantity = quantity + ? WHERE id = ?",
            (sale["quantity_sold"], sale["product_id"])
        )
        conn.execute(
            "DELETE FROM sales WHERE id = ?", (sale_id,)
        )
        conn.commit()

    conn.close()
    return redirect(url_for("sales"))


@app.route("/delete/<int:pid>")
@login_required
def delete_product(pid):
    conn = get_db()
    product = conn.execute(
        "SELECT type FROM products WHERE id = ?", (pid,)
    ).fetchone()

    conn.execute("DELETE FROM products WHERE id = ?", (pid,))
    conn.commit()
    conn.close()

    return redirect(url_for("index", type=product["type"]))


# ===============================
# تشغيل
# ===============================

init_db()

if __name__ == "__main__":
    app.run()
