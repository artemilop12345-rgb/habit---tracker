"""
Habit Tracker — простой трекер привычек.
Это твой главный файл. Здесь живёт вся "логика" сайта:
какие страницы существуют (маршруты), что они делают,
и как они общаются с базой данных.
"""

from flask import Flask, render_template, request, redirect, url_for
import sqlite3
from datetime import date, timedelta

app = Flask(__name__)
DB_NAME = "habits.db"


def get_connection():
    """Открывает соединение с базой данных SQLite."""
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row  # позволяет обращаться к колонкам по имени
    return conn


def init_db():
    """Создаёт таблицы, если их ещё нет. Вызывается один раз при старте."""
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS habits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL
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

def calculate_streak(conn, habit_id):
    """
    Считаем текущий стрик (серию дней подряд без пропуска) для привычки.
    Идём от сегодняшнего дня назад: если день отмечен - увеличиваем стрик
    и переходим к предыдущему дню; как только встретили пропущенный день
    (и это не "сегодня", которое может быть ещё не отмечено) - останавливаемся.
    """
    rows = conn.execute(
        "SELECT log_date FROM logs WHERE habit_id = ? ORDER BY log_date DESC",
        (habit_id,)
    ).fetchall()
    done_dates = {row["log_date"] for row in rows}

    streak = 0
    current_day = date.today()

    if current_day.isoformat() not in done_dates:
        current_day -= timedelta(days=1)

    while current_day.isoformat()in done_dates:
        streak += 1
        current_day -= timedelta(days=1)
    return streak

@app.route("/")
def index():
    """Главная страница: показывает список всех привычек."""
    conn = get_connection()
    habits = conn.execute("SELECT * FROM habits").fetchall()

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
            "id": habit["id"],
            "name": habit["name"],
            "done_today": done_today is not None,
            "total_count": total_count,
            "streak": streak
        })

    conn.close()
    return render_template("index.html", habits=habits_with_status, today=today)


@app.route("/add", methods=["POST"])
def add_habit():
    """Добавляет новую привычку (вызывается из формы на странице)."""
    name = request.form.get("name")
    if name:
        conn = get_connection()
        conn.execute("INSERT INTO habits (name) VALUES (?)", (name,))
        conn.commit()
        conn.close()
    return redirect(url_for("index"))


@app.route("/check/<int:habit_id>", methods=["POST"])
def check_habit(habit_id):
    """Отмечает привычку как выполненную сегодня."""
    today = date.today().isoformat()
    conn = get_connection()
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
def delete_habit(habit_id):
    """Удаляет привычку и всю её историю."""
    conn = get_connection()
    conn.execute("DELETE FROM logs WHERE habit_id = ?", (habit_id,))
    conn.execute("DELETE FROM habits WHERE id = ?", (habit_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("index"))


if __name__ == "__main__":
    init_db()
    app.run(debug=True)