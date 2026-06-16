"""
Habit Tracker — трекер привычек с поддержкой пользователей.
Каждый пользователь видит и редактирует только свои привычки.
"""

from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
from datetime import date, timedelta
from functools import wraps

app = Flask(__name__)
app.secret_key = "change-this-secret-key-to-something-random" # нужен для подписи сессий
DB_NAME = "habits.db"

def get_connection():
    """Открывает соединение с базой данных SQLite"""
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Создаёт таблицы, если их ещё нет."""
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS habits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            habit_id INTEGER NOT NULL,
            log_date TEXT NOT NULL,
            FOREIGN KEY (habit_id) REFERENCES habits (id)
        )
    """)
    conn.commit()
    conn.close()

def login_required(view_func):
    """
    Декоратор: оборачивает функцию-маршрут так, чтобы перед её выполнением
    проверялось, вошёл ли пользователь. Если нет - отправляем на /login.
    Используем так: ставим @login_required прямо над @app.route.
    """
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return view_func(*args, **kwargs)
    return wrapped

def calculate_streak(conn, habit_id):
    """Считает текущий стрик(серию дней подряд без пропуска) для привыычки."""
    rows = conn.execute(
        "SELECT log_date FROM logs WHERE habit_id = ? ORDER BY log_date DESC",
        (habit_id,)
    ).fetchall()
    done_dates={row["log_date"] for row in rows}

    streak = 0
    current_day = date.today()

    if current_day.isoformat() not in done_dates:
        current_day -= timedelta(days=1)

    while current_day.isoformat() in done_dates:
        streak += 1
        current_day -= timedelta(days=1)
    return streak
@app.route("/register", methods=["GET","POST"])
def register():
    """Регистрация нового пользователя."""
    if request.method == "POST":
        username = request.form.get("username","").strip()
        password = request.form.get("password","")

        if not username or not password:
            flash("Заполните логин и пароль")
            return redirect(url_for("register"))

        conn = get_connection()
        existing = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
        if existing:
            flash("Этот логин уже занят")
            conn.close()
            return redirect(url_for("register"))

        password_hash = generate_password_hash(password)
        conn.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (username, password_hash)
        )
        conn.commit()
        conn.close()
        flash("Регистрация успешна! Теперь войдите.")
        return redirect(url_for("login"))

    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    """Вход пользователя."""
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        conn = get_connection()
        user = conn.execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
        conn.close()

        if user is None or not check_password_hash(user["password_hash"], password):
            flash("Неверный логин или пароль")
            return redirect(url_for("login"))

        session["user_id"] = user["id"]
        session["username"] = user["username"]
        return redirect(url_for("index"))

    return render_template("login.html")

@app.route("/logout")
def logout():
    """Выход пользователя — очищаем сессию."""
    session.clear()
    return redirect(url_for("login"))

@app.route("/")
@login_required
def index():
    """Главная страница: показывает привычки только текущего пользователя."""
    conn = get_connection()
    user_id = session["user_id"]
    habits = conn.execute(
        "SELECT * FROM habits WHERE user_id = ?", (user_id,)
    ).fetchall()

    today = date.today().isoformat()
    habits_with_status = []
    for habit in habits:
        done_today = conn.execute(
            "SELECT * FROM logs WHERE habit_id = ? AND log_date = ?",
            (habit["id"], today)
        ).fetchone()
        total_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM logs WHERE habit_id = ?",
            (habit["id"],)
        ).fetchone()["cnt"]
        streak = calculate_streak(conn, habit["id"])
        habits_with_status.append({
            "id":habit["id"],
            "name": habit["name"],
            "done_today": done_today is not None,
            "total_count": total_count,
            "streak": streak
        })

    conn.close()
    return render_template(
        "index.html",
        habits=habits_with_status,
        today =today,
        username=session.get("username")
    )
@app.route("/add", methods=["POST"])
@login_required
def add_habit():
    """Добавляет новую привычку для текущего пользователя."""
    name = request.form.get("name")
    if name:
        conn = get_connection()
        conn.execute(
            "INSERT INTO habits (user_id, name) VALUES (?, ?)",
            (session["user_id"],name)
        )
        conn.commit()
        conn.close()
    return redirect(url_for("index"))


def _habit_belongs_to_user(conn, habit_id, user_id):
    """Проверяет, что привычка принадлежит текущему пользователю."""
    habit = conn.execute(
        "SELECT * FROM habits WHERE id = ? AND user_id = ?",
        (habit_id, user_id)
    ).fetchone()
    return habit is not None


@app.route("/check/<int:habit_id>", methods=["POST"])
@login_required
def check_habit(habit_id):
    """Отмечает привычку как выполненную сегодня (только если она своя)."""
    conn = get_connection()
    if not _habit_belongs_to_user(conn, habit_id, session["user_id"]):
        conn.close()
        return redirect(url_for("index"))

    today = date.today().isoformat()
    already = conn.execute(
        "SELECT * FROM logs WHERE habit_id = ? AND log_date = ?",
        (habit_id, today)
    ).fetchone()
    if not already:
        conn.execute(
            "INSERT INTO logs (habit_id, log_date) VALUES (?, ?)",
            (habit_id, today)
        )
        conn.commit()
    conn.close()
    return redirect(url_for("index"))


@app.route("/delete/<int:habit_id>", methods=["POST"])
@login_required
def delete_habit(habit_id):
    """Удаляет привычку (только если она своя)."""
    conn = get_connection()
    if not _habit_belongs_to_user(conn, habit_id, session["user_id"]):
        conn.close()
        return redirect(url_for("index"))

    conn.execute("DELETE FROM logs WHERE habit_id = ?", (habit_id,))
    conn.execute("DELETE FROM habits WHERE id = ?", (habit_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("index"))


if __name__ == "__main__":
    init_db()
    app.run(debug=True)