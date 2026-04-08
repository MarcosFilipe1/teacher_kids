import sqlite3
import os
from datetime import datetime

DB_PATH = os.environ.get("DB_PATH", "eduapp.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()

    c.executescript("""
        CREATE TABLE IF NOT EXISTS profiles (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            type        TEXT NOT NULL CHECK(type IN ('noah','aurora')),
            age_months  INTEGER NOT NULL,
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS sessions (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id       INTEGER NOT NULL REFERENCES profiles(id),
            activity_type    TEXT NOT NULL,
            duration_seconds INTEGER DEFAULT 0,
            started_at       DATETIME DEFAULT CURRENT_TIMESTAMP,
            ended_at         DATETIME
        );

        CREATE TABLE IF NOT EXISTS word_attempts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  INTEGER NOT NULL REFERENCES sessions(id),
            word_pt     TEXT NOT NULL,
            word_en     TEXT NOT NULL,
            correct     INTEGER NOT NULL DEFAULT 0,
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS aurora_sessions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  INTEGER NOT NULL REFERENCES sessions(id),
            category    TEXT NOT NULL,
            tip_shown   TEXT,
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS api_usage (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  INTEGER REFERENCES sessions(id),
            provider    TEXT NOT NULL,
            tokens_in   INTEGER DEFAULT 0,
            tokens_out  INTEGER DEFAULT 0,
            cost_usd    REAL DEFAULT 0,
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS weekly_reports (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            week_start            DATE NOT NULL,
            noah_sessions         INTEGER DEFAULT 0,
            noah_minutes          INTEGER DEFAULT 0,
            noah_words_practiced  INTEGER DEFAULT 0,
            noah_words_correct    INTEGER DEFAULT 0,
            noah_hardest_words    TEXT,
            aurora_sessions       INTEGER DEFAULT 0,
            aurora_categories     TEXT,
            total_cost_usd        REAL DEFAULT 0,
            summary_text          TEXT,
            sent_at               DATETIME
        );
    """)

    # Seed profiles se ainda não existirem
    existing = c.execute("SELECT COUNT(*) FROM profiles").fetchone()[0]
    if existing == 0:
        c.execute("INSERT INTO profiles (name, type, age_months) VALUES ('Noah', 'noah', 72)")
        c.execute("INSERT INTO profiles (name, type, age_months) VALUES ('Aurora', 'aurora', 10)")

    conn.commit()
    conn.close()
    print(f"[DB] Banco inicializado em {DB_PATH}")


# ─── helpers de sessão ───────────────────────────────────────────────────────

def start_session(profile_id: int, activity_type: str) -> int:
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "INSERT INTO sessions (profile_id, activity_type) VALUES (?, ?)",
        (profile_id, activity_type)
    )
    session_id = c.lastrowid
    conn.commit()
    conn.close()
    return session_id


def end_session(session_id: int):
    conn = get_db()
    conn.execute(
        "UPDATE sessions SET ended_at = CURRENT_TIMESTAMP, "
        "duration_seconds = CAST((julianday(CURRENT_TIMESTAMP) - julianday(started_at)) * 86400 AS INTEGER) "
        "WHERE id = ?",
        (session_id,)
    )
    conn.commit()
    conn.close()


def log_word_attempt(session_id: int, word_pt: str, word_en: str, correct: bool):
    conn = get_db()
    conn.execute(
        "INSERT INTO word_attempts (session_id, word_pt, word_en, correct) VALUES (?,?,?,?)",
        (session_id, word_pt, word_en, int(correct))
    )
    conn.commit()
    conn.close()


def log_aurora_session(session_id: int, category: str, tip_shown: str = None):
    conn = get_db()
    conn.execute(
        "INSERT INTO aurora_sessions (session_id, category, tip_shown) VALUES (?,?,?)",
        (session_id, category, tip_shown)
    )
    conn.commit()
    conn.close()


def log_api_usage(session_id: int, provider: str, tokens_in: int, tokens_out: int, cost_usd: float):
    conn = get_db()
    conn.execute(
        "INSERT INTO api_usage (session_id, provider, tokens_in, tokens_out, cost_usd) VALUES (?,?,?,?,?)",
        (session_id, provider, tokens_in, tokens_out, cost_usd)
    )
    conn.commit()
    conn.close()


# ─── queries para relatório ──────────────────────────────────────────────────

def get_weekly_stats(week_start: str) -> dict:
    """Retorna dados da semana para o relatório. week_start = 'YYYY-MM-DD' (domingo)"""
    conn = get_db()
    c = conn.cursor()

    # Noah
    noah = c.execute("""
        SELECT
            COUNT(DISTINCT s.id)                        AS sessions,
            COALESCE(SUM(s.duration_seconds) / 60, 0)  AS minutes,
            COUNT(wa.id)                                AS words_practiced,
            COALESCE(SUM(wa.correct), 0)               AS words_correct
        FROM sessions s
        LEFT JOIN word_attempts wa ON wa.session_id = s.id
        WHERE s.profile_id = (SELECT id FROM profiles WHERE type='noah')
          AND DATE(s.started_at) >= DATE(?)
          AND DATE(s.started_at) < DATE(?, '+7 days')
    """, (week_start, week_start)).fetchone()

    hardest = c.execute("""
        SELECT word_pt, word_en, COUNT(*) as erros
        FROM word_attempts wa
        JOIN sessions s ON s.id = wa.session_id
        WHERE wa.correct = 0
          AND s.profile_id = (SELECT id FROM profiles WHERE type='noah')
          AND DATE(s.started_at) >= DATE(?)
          AND DATE(s.started_at) < DATE(?, '+7 days')
        GROUP BY word_pt
        ORDER BY erros DESC
        LIMIT 5
    """, (week_start, week_start)).fetchall()

    # Aurora
    aurora = c.execute("""
        SELECT
            COUNT(DISTINCT s.id)        AS sessions,
            GROUP_CONCAT(DISTINCT aus.category) AS categories
        FROM sessions s
        LEFT JOIN aurora_sessions aus ON aus.session_id = s.id
        WHERE s.profile_id = (SELECT id FROM profiles WHERE type='aurora')
          AND DATE(s.started_at) >= DATE(?)
          AND DATE(s.started_at) < DATE(?, '+7 days')
    """, (week_start, week_start)).fetchone()

    # Custo total
    cost = c.execute("""
        SELECT COALESCE(SUM(cost_usd), 0) AS total
        FROM api_usage
        WHERE DATE(created_at) >= DATE(?)
          AND DATE(created_at) < DATE(?, '+7 days')
    """, (week_start, week_start)).fetchone()

    conn.close()

    return {
        "week_start": week_start,
        "noah": {
            "sessions": noah["sessions"] or 0,
            "minutes": noah["minutes"] or 0,
            "words_practiced": noah["words_practiced"] or 0,
            "words_correct": noah["words_correct"] or 0,
            "accuracy_pct": round(
                (noah["words_correct"] / noah["words_practiced"] * 100)
                if noah["words_practiced"] else 0
            ),
            "hardest_words": [dict(r) for r in hardest],
        },
        "aurora": {
            "sessions": aurora["sessions"] or 0,
            "categories": aurora["categories"] or "",
        },
        "cost_usd": round(cost["total"], 4),
    }
