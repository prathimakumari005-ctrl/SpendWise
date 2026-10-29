from flask import (
    Flask, render_template, request,
    redirect, url_for, session, flash
)
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from datetime import datetime
import sqlite3
import os

app = Flask(__name__)
app.secret_key = os.environ.get(
    "SECRET_KEY",
    "development-secret-change-before-deployment"
)

DATABASE = "spendwise.db"


# DATABASE CONNECTION
def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


# CREATE TABLES WITHOUT DELETING EXISTING DATA
def init_db():
    conn = get_db()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            category TEXT NOT NULL,
            amount REAL NOT NULL,
            type TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    conn.commit()
    conn.close()


# LOGIN PROTECTION
def login_required(route_function):
    @wraps(route_function)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return route_function(*args, **kwargs)
    return wrapper


# DASHBOARD
@app.route("/")
@login_required
def home():
    user_id = session["user_id"]
    conn = get_db()

    transactions = conn.execute("""
        SELECT * FROM transactions
        WHERE user_id = ?
        ORDER BY id DESC
    """, (user_id,)).fetchall()

    total_income = conn.execute("""
        SELECT COALESCE(SUM(amount), 0)
        FROM transactions
        WHERE user_id = ? AND type = 'Income'
    """, (user_id,)).fetchone()[0]

    total_expenses = conn.execute("""
        SELECT COALESCE(SUM(amount), 0)
        FROM transactions
        WHERE user_id = ? AND type = 'Expense'
    """, (user_id,)).fetchone()[0]

    conn.close()

    balance = total_income - total_expenses

    return render_template(
        "index.html",
        name=session["name"],
        transactions=transactions,
        total_income=total_income,
        total_expenses=total_expenses,
        balance=balance,
        total_savings=0
    )


# REGISTRATION
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        if not name or not email or not password:
            flash("Please fill in every field.")
            return render_template("register.html")

        if len(password) < 8:
            flash("Password must contain at least 8 characters.")
            return render_template("register.html")

        conn = get_db()

        try:
            conn.execute("""
                INSERT INTO users (name, email, password)
                VALUES (?, ?, ?)
            """, (
                name,
                email,
                generate_password_hash(password)
            ))
            conn.commit()

        except sqlite3.IntegrityError:
            flash("This email is already registered.")
            return render_template("register.html")

        finally:
            conn.close()

        flash("Registration successful! Please log in.")
        return redirect(url_for("login"))

    return render_template("register.html")


# LOGIN
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        conn = get_db()
        user = conn.execute("""
            SELECT * FROM users WHERE email = ?
        """, (email,)).fetchone()
        conn.close()

        if user and check_password_hash(user["password"], password):
            session.clear()
            session["user_id"] = user["id"]
            session["name"] = user["name"]
            return redirect(url_for("home"))

        flash("Incorrect email or password.")

    return render_template("login.html")


# ADD INCOME OR EXPENSE
@app.route("/add/<transaction_type>", methods=["GET", "POST"])
@login_required
def add_transaction(transaction_type):
    if transaction_type not in ["income", "expense"]:
        return "Invalid transaction type", 404

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        category = request.form.get("category", "").strip()

        try:
            amount = float(request.form.get("amount", ""))
        except (ValueError, TypeError):
            amount = 0

        if not title or not category or amount <= 0:
            flash("Enter a description, category and valid amount.")
        else:
            conn = get_db()

            conn.execute("""
                INSERT INTO transactions
                    (user_id, title, category, amount, type)
                VALUES (?, ?, ?, ?, ?)
            """, (
                session["user_id"],
                title,
                category,
                amount,
                transaction_type.title()
            ))

            conn.commit()
            conn.close()

            flash(f"{transaction_type.title()} saved successfully!")
            return redirect(url_for("home"))

    return render_template(
        "add_transaction.html",
        transaction_type=transaction_type.title()
    )


# EDIT A TRANSACTION
@app.route("/edit/<int:transaction_id>", methods=["GET", "POST"])
@login_required
def edit_transaction(transaction_id):
    conn = get_db()

    transaction = conn.execute("""
        SELECT * FROM transactions
        WHERE id = ? AND user_id = ?
    """, (transaction_id, session["user_id"])).fetchone()

    if transaction is None:
        conn.close()
        return "Transaction not found", 404

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        category = request.form.get("category", "").strip()
        transaction_type = request.form.get("type", "")
        transaction_type = transaction_type.title()

        try:
            amount = float(request.form.get("amount", ""))
        except (ValueError, TypeError):
            amount = 0

        if (
            not title
            or not category
            or transaction_type not in ["Income", "Expense"]
            or amount <= 0
        ):
            flash("Please enter valid transaction details.")
            conn.close()
            return redirect(url_for(
                "edit_transaction",
                transaction_id=transaction_id
            ))

        conn.execute("""
            UPDATE transactions
            SET title = ?, category = ?, amount = ?, type = ?
            WHERE id = ? AND user_id = ?
        """, (
            title,
            category,
            amount,
            transaction_type,
            transaction_id,
            session["user_id"]
        ))

        conn.commit()
        conn.close()

        flash("Transaction updated successfully!")
        return redirect(url_for("home"))

    conn.close()

    return render_template(
        "edit_transaction.html",
        transaction=transaction
    )


# DELETE A TRANSACTION
@app.route("/delete/<int:transaction_id>", methods=["POST"])
@login_required
def delete_transaction(transaction_id):
    conn = get_db()

    conn.execute("""
        DELETE FROM transactions
        WHERE id = ? AND user_id = ?
    """, (transaction_id, session["user_id"]))

    conn.commit()
    conn.close()

    flash("Transaction deleted successfully!")
    return redirect(url_for("home"))


# MONTHLY TRANSACTION REPORT
@app.route("/reports")
@login_required
def reports():
    current_month = datetime.now().strftime("%Y-%m")
    month = request.args.get("month", current_month)

    try:
        datetime.strptime(month, "%Y-%m")
    except ValueError:
        month = current_month

    user_id = session["user_id"]
    conn = get_db()

    transactions = conn.execute("""
        SELECT * FROM transactions
        WHERE user_id = ?
          AND strftime('%Y-%m', created_at) = ?
        ORDER BY id DESC
    """, (user_id, month)).fetchall()

    total_income = conn.execute("""
        SELECT COALESCE(SUM(amount), 0)
        FROM transactions
        WHERE user_id = ?
          AND type = 'Income'
          AND strftime('%Y-%m', created_at) = ?
    """, (user_id, month)).fetchone()[0]

    total_expenses = conn.execute("""
        SELECT COALESCE(SUM(amount), 0)
        FROM transactions
        WHERE user_id = ?
          AND type = 'Expense'
          AND strftime('%Y-%m', created_at) = ?
    """, (user_id, month)).fetchone()[0]

    categories = conn.execute("""
        SELECT category, SUM(amount) AS total
        FROM transactions
        WHERE user_id = ?
          AND type = 'Expense'
          AND strftime('%Y-%m', created_at) = ?
        GROUP BY category
        ORDER BY total DESC
    """, (user_id, month)).fetchall()

    conn.close()

    return render_template(
        "reports.html",
        name=session["name"],
        month=month,
        transactions=transactions,
        total_income=total_income,
        total_expenses=total_expenses,
        balance=total_income - total_expenses,
        categories=categories
    )


# LOGOUT
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


if __name__ == "__main__":
    init_db()
    app.run(host="127.0.0.1", port=5000, debug=True)	

