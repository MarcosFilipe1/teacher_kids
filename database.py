import sqlite3
import os
from datetime import date

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
            type        TEXT NOT NULL,
            age_months  INTEGER NOT NULL,
            created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS progress (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id      INTEGER NOT NULL REFERENCES profiles(id),
            current_phase   INTEGER DEFAULT 1,
            current_step    INTEGER DEFAULT 1,
            total_xp        INTEGER DEFAULT 0,
            dino_stage      INTEGER DEFAULT 0,
            streak_days     INTEGER DEFAULT 0,
            last_activity   DATE,
            updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS sessions (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            profile_id       INTEGER NOT NULL REFERENCES profiles(id),
            phase            INTEGER DEFAULT 1,
            step             INTEGER DEFAULT 1,
            activity_type    TEXT NOT NULL,
            duration_seconds INTEGER DEFAULT 0,
            xp_earned        INTEGER DEFAULT 0,
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

    existing = c.execute("SELECT COUNT(*) FROM profiles").fetchone()[0]
    if existing == 0:
        c.execute("INSERT INTO profiles (name, type, age_months) VALUES ('Noah', 'noah', 72)")
        c.execute("INSERT INTO profiles (name, type, age_months) VALUES ('Aurora', 'aurora', 10)")
        c.execute("INSERT INTO progress (profile_id) VALUES (1)")

    conn.commit()
    conn.close()
    print(f"[DB] Banco inicializado em {DB_PATH}")


def get_progress(profile_id: int) -> dict:
    conn = get_db()
    row = conn.execute("SELECT * FROM progress WHERE profile_id = ?", (profile_id,)).fetchone()
    conn.close()
    if not row:
        return {"current_phase": 1, "current_step": 1, "total_xp": 0, "dino_stage": 0, "streak_days": 0}
    return dict(row)


def update_progress(profile_id: int, xp_earned: int, completed_step: bool = False) -> dict:
    conn = get_db()
    prog = conn.execute("SELECT * FROM progress WHERE profile_id = ?", (profile_id,)).fetchone()
    if not prog:
        conn.close()
        return {}

    new_xp = prog["total_xp"] + xp_earned
    phase = prog["current_phase"]
    step = prog["current_step"]
    dino = prog["dino_stage"]
    phase_changed = False

    if completed_step:
        step += 1
        if step > 3:
            step = 1
            phase = min(phase + 1, 4)
            dino = min(phase - 1, 3)
            phase_changed = True

    today = str(date.today())
    last = prog["last_activity"]
    streak = prog["streak_days"]
    if last == today:
        pass
    elif last and (date.today() - date.fromisoformat(last)).days == 1:
        streak += 1
    else:
        streak = 1

    conn.execute("""
        UPDATE progress SET current_phase=?, current_step=?, total_xp=?,
        dino_stage=?, streak_days=?, last_activity=?, updated_at=CURRENT_TIMESTAMP
        WHERE profile_id=?
    """, (phase, step, new_xp, dino, streak, today, profile_id))
    conn.commit()
    conn.close()

    return {
        "current_phase": phase, "current_step": step,
        "total_xp": new_xp, "dino_stage": dino,
        "streak_days": streak, "phase_changed": phase_changed,
    }


def start_session(profile_id: int, activity_type: str, phase: int = 1, step: int = 1) -> int:
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO sessions (profile_id, activity_type, phase, step) VALUES (?,?,?,?)",
              (profile_id, activity_type, phase, step))
    sid = c.lastrowid
    conn.commit()
    conn.close()
    return sid


def end_session(session_id: int, xp_earned: int = 0):
    conn = get_db()
    conn.execute("""
        UPDATE sessions SET ended_at=CURRENT_TIMESTAMP, xp_earned=?,
        duration_seconds=CAST((julianday(CURRENT_TIMESTAMP)-julianday(started_at))*86400 AS INTEGER)
        WHERE id=?
    """, (xp_earned, session_id))
    conn.commit()
    conn.close()


def log_word_attempt(session_id: int, word_pt: str, word_en: str, correct: bool):
    conn = get_db()
    conn.execute("INSERT INTO word_attempts (session_id,word_pt,word_en,correct) VALUES (?,?,?,?)",
                 (session_id, word_pt, word_en, int(correct)))
    conn.commit()
    conn.close()


def log_aurora_session(session_id: int, category: str, tip_shown: str = None):
    conn = get_db()
    conn.execute("INSERT INTO aurora_sessions (session_id,category,tip_shown) VALUES (?,?,?)",
                 (session_id, category, tip_shown))
    conn.commit()
    conn.close()


def log_api_usage(session_id: int, provider: str, tokens_in: int, tokens_out: int, cost_usd: float):
    conn = get_db()
    conn.execute("INSERT INTO api_usage (session_id,provider,tokens_in,tokens_out,cost_usd) VALUES (?,?,?,?,?)",
                 (session_id, provider, tokens_in, tokens_out, cost_usd))
    conn.commit()
    conn.close()


def get_weekly_stats(week_start: str) -> dict:
    conn = get_db()
    c = conn.cursor()
    noah = c.execute("""
        SELECT COUNT(DISTINCT s.id) AS sessions,
               COALESCE(SUM(s.duration_seconds)/60,0) AS minutes,
               COUNT(wa.id) AS words_practiced,
               COALESCE(SUM(wa.correct),0) AS words_correct
        FROM sessions s LEFT JOIN word_attempts wa ON wa.session_id=s.id
        WHERE s.profile_id=(SELECT id FROM profiles WHERE type='noah')
          AND DATE(s.started_at)>=DATE(?) AND DATE(s.started_at)<DATE(?,'+7 days')
    """, (week_start, week_start)).fetchone()
    hardest = c.execute("""
        SELECT word_pt, word_en, COUNT(*) as erros
        FROM word_attempts wa JOIN sessions s ON s.id=wa.session_id
        WHERE wa.correct=0 AND s.profile_id=(SELECT id FROM profiles WHERE type='noah')
          AND DATE(s.started_at)>=DATE(?) AND DATE(s.started_at)<DATE(?,'+7 days')
        GROUP BY word_pt ORDER BY erros DESC LIMIT 5
    """, (week_start, week_start)).fetchall()
    aurora = c.execute("""
        SELECT COUNT(DISTINCT s.id) AS sessions, GROUP_CONCAT(DISTINCT aus.category) AS categories
        FROM sessions s LEFT JOIN aurora_sessions aus ON aus.session_id=s.id
        WHERE s.profile_id=(SELECT id FROM profiles WHERE type='aurora')
          AND DATE(s.started_at)>=DATE(?) AND DATE(s.started_at)<DATE(?,'+7 days')
    """, (week_start, week_start)).fetchone()
    cost = c.execute("""
        SELECT COALESCE(SUM(cost_usd),0) AS total FROM api_usage
        WHERE DATE(created_at)>=DATE(?) AND DATE(created_at)<DATE(?,'+7 days')
    """, (week_start, week_start)).fetchone()
    conn.close()
    return {
        "week_start": week_start,
        "noah": {
            "sessions": noah["sessions"] or 0, "minutes": noah["minutes"] or 0,
            "words_practiced": noah["words_practiced"] or 0, "words_correct": noah["words_correct"] or 0,
            "accuracy_pct": round((noah["words_correct"]/noah["words_practiced"]*100) if noah["words_practiced"] else 0),
            "hardest_words": [dict(r) for r in hardest],
        },
        "aurora": {"sessions": aurora["sessions"] or 0, "categories": aurora["categories"] or ""},
        "cost_usd": round(cost["total"], 4),
    }
