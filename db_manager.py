import sqlite3
from datetime import datetime

DB_NAME = "database.db"

def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT UNIQUE,
                username TEXT
            )''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                test_name TEXT UNIQUE,
                time_limit INTEGER
            )''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                test_id INTEGER,
                score_percent REAL,
                completed_at DATETIME,
                FOREIGN KEY(user_id) REFERENCES users(user_id),
                FOREIGN KEY(test_id) REFERENCES tests(id)
            )''')
        conn.commit()

def save_user(user_id: str, username: str):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user_id, username))
        conn.commit()

def save_test(test_name: str, time_limit: int):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO tests (test_name, time_limit) VALUES (?, ?)", (test_name, time_limit))
        conn.commit()
        cursor.execute("SELECT id FROM tests WHERE test_name = ?", (test_name,))
        return cursor.fetchone()[0]

def save_result(user_id: str, test_id: int, score_percent: float):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO results (user_id, test_id, score_percent, completed_at)
            VALUES (?, ?, ?, ?)
        """, (user_id, test_id, score_percent, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()

def get_user_results(user_id: str):
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT t.test_name, r.score_percent, r.completed_at 
            FROM results r 
            JOIN tests t ON r.test_id = t.id 
            WHERE r.user_id = ?
            ORDER BY r.completed_at DESC
        """, (user_id,))
        return cursor.fetchall()
