import os
import base64
import logging
from flask import Flask, request, jsonify, render_template
from dotenv import load_dotenv

load_dotenv()

from database import (
    init_db, get_db, get_progress, update_progress,
    start_session, end_session, log_word_attempt,
    log_aurora_session, log_api_usage
)
from teacher import luna_start_activity, luna_respond, luna_free_talk, get_aurora_tip
from voice import text_to_speech, speech_to_text, estimate_tts_cost

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "eduapp-secret-2025")

active_sessions = {}
conversation_histories = {}
activity_states = {}


@app.route("/")
def index(): return render_template("index.html")

@app.route("/noah")
def noah(): return render_template("noah.html")

@app.route("/aurora")
def aurora(): return render_template("aurora.html")


@app.route("/api/progress/<profile_type>")
def api_get_progress(profile_type):
    conn = get_db()
    p = conn.execute("SELECT id FROM profiles WHERE type=?", (profile_type,)).fetchone()
    conn.close()
    return jsonify(get_progress(p["id"])) if p else (jsonify({"error": "não encontrado"}), 404)


@app.route("/api/progress/complete-step", methods=["POST"])
def api_complete_step():
    data = request.json
    profile_type = data.get("profile", "noah")
    xp = data.get("xp", 30)
    conn = get_db()
    p = conn.execute("SELECT id FROM profiles WHERE type=?", (profile_type,)).fetchone()
    conn.close()
    result = update_progress(p["id"], xp, completed_step=True)
    sid = active_sessions.get(profile_type)
    if sid: end_session(sid, xp)
    return jsonify(result)


@app.route("/api/session/start", methods=["POST"])
def api_start_session():
    data = request.json
    profile_type = data.get("profile")
    activity = data.get("activity", "words")
    phase = data.get("phase", 1)
    step_num = data.get("step", 1)
    word_set = data.get("word_set", [])
    word_set_key = data.get("word_set_key", "animals")

    conn = get_db()
    p = conn.execute("SELECT id FROM profiles WHERE type=?", (profile_type,)).fetchone()
    conn.close()
    if not p: return jsonify({"error": "não encontrado"}), 404

    sid = start_session(p["id"], activity, phase, step_num)
    active_sessions[profile_type] = sid
    conversation_histories[sid] = []
    activity_states[sid] = {
        "activity_type": f"{activity}_{word_set_key}",
        "word_set": word_set,
        "word_idx": 0,
        "attempts": 0,
        "consecutive_correct": 0,
        "consecutive_errors": 0,
        "total_correct": 0,
    }
    logger.info(f"[Session] {profile_type} fase {phase} step {step_num} id={sid}")
    return jsonify({"session_id": sid})


@app.route("/api/session/end", methods=["POST"])
def api_end_session():
    data = request.json
    profile_type = data.get("profile")
    xp = data.get("xp", 0)
    sid = active_sessions.get(profile_type)
    if sid:
        end_session(sid, xp)
        for d in [conversation_histories, activity_states, active_sessions]:
            d.pop(profile_type if d is active_sessions else sid, None)
    return jsonify({"ok": True})


@app.route("/api/luna/start", methods=["POST"])
def api_luna_start():
    """Luna fala ao abrir o passo da trilha."""
    data = request.json
    profile_type = data.get("profile", "noah")
    activity_type = data.get("activity_type", "words_animals")
    word_set = data.get("word_set", [])
    sid = active_sessions.get(profile_type)

    result = luna_start_activity(activity_type, word_set, sid)

    if sid:
        history = conversation_histories.get(sid, [])
        history.append({"role": "assistant", "content": result["text"]})
        conversation_histories[sid] = history

    audio_bytes = text_to_speech(result["text"], voice="nova")
    audio_b64 = base64.b64encode(audio_bytes).decode() if audio_bytes else ""
    if sid and audio_bytes:
        log_api_usage(sid, "openai_tts", 0, 0, estimate_tts_cost(result["text"]))

    return jsonify({"text": result["text"], "audio_b64": audio_b64,
                    "action": result.get("action"), "cost_usd": result["cost_usd"]})


@app.route("/api/luna/respond", methods=["POST"])
def api_luna_respond():
    """Noah falou — Luna avalia, responde e decide próximo passo."""
    data = request.json
    profile_type = data.get("profile", "noah")
    child_said = data.get("child_said", "")
    is_word_attempt = data.get("is_word_attempt", True)

    sid = active_sessions.get(profile_type)
    history = conversation_histories.get(sid, [])
    state = activity_states.get(sid, {})

    # Palavra atual
    current_word = {}
    ws = state.get("word_set", [])
    idx = state.get("word_idx", 0)
    if ws and idx < len(ws):
        current_word = ws[idx]

    correct = False
    xp = 2
    prog = {}

    if is_word_attempt and current_word:
        # Checa acerto
        said = child_said.lower().strip()
        en = current_word.get("en", "").lower().strip()
        pt = current_word.get("pt", "").lower().strip()
        correct = en in said or said in en or pt in said

        state["attempts"] = state.get("attempts", 0) + 1
        if correct:
            state["consecutive_correct"] = state.get("consecutive_correct", 0) + 1
            state["consecutive_errors"] = 0
            state["total_correct"] = state.get("total_correct", 0) + 1
            xp = 10
        else:
            state["consecutive_errors"] = state.get("consecutive_errors", 0) + 1
            state["consecutive_correct"] = 0
            xp = 3

        if sid:
            log_word_attempt(sid, current_word.get("pt", ""), current_word.get("en", ""), correct)

        result = luna_respond(
            child_said=child_said,
            activity_type=state.get("activity_type", "words_animals"),
            current_word=current_word,
            correct=correct,
            attempts=state["attempts"],
            consecutive_correct=state["consecutive_correct"],
            consecutive_errors=state["consecutive_errors"],
            conversation_history=history,
            session_id=sid,
        )

        # Atualiza XP
        conn = get_db()
        p = conn.execute("SELECT id FROM profiles WHERE type=?", (profile_type,)).fetchone()
        conn.close()
        if p: prog = update_progress(p["id"], xp)

        # Avança palavra
        action = result.get("action")
        if action == "PRÓXIMA":
            state["word_idx"] = idx + 1
            state["attempts"] = 0
            state["consecutive_correct"] = 0
            state["consecutive_errors"] = 0
            if state["word_idx"] >= len(ws):
                result["action"] = "COMPLETO"
    else:
        result = luna_free_talk(
            child_said=child_said,
            activity_type=state.get("activity_type", "words_animals"),
            current_word=current_word,
            conversation_history=history,
            session_id=sid,
        )

    if sid:
        activity_states[sid] = state

    # Histórico
    history.append({"role": "user", "content": child_said})
    history.append({"role": "assistant", "content": result["text"]})
    if sid: conversation_histories[sid] = history[-12:]

    # TTS
    audio_bytes = text_to_speech(result["text"], voice="nova")
    audio_b64 = base64.b64encode(audio_bytes).decode() if audio_bytes else ""
    if sid and audio_bytes:
        log_api_usage(sid, "openai_tts", 0, 0, estimate_tts_cost(result["text"]))

    # Próxima palavra
    new_idx = state.get("word_idx", 0)
    next_word = ws[new_idx] if ws and new_idx < len(ws) else None

    return jsonify({
        "text": result["text"], "audio_b64": audio_b64,
        "action": result.get("action"), "correct": correct,
        "xp_earned": xp, "progress": prog,
        "next_word": next_word, "word_idx": new_idx,
        "cost_usd": result["cost_usd"],
    })


@app.route("/api/voice/listen", methods=["POST"])
def api_voice_listen():
    if "audio" not in request.files:
        return jsonify({"error": "sem áudio"}), 400
    text = speech_to_text(request.files["audio"].read(), language="pt")
    return jsonify({"text": text})


@app.route("/api/aurora/tip", methods=["POST"])
def api_aurora_tip():
    data = request.json
    category = data.get("category", "sons")
    sid = active_sessions.get("aurora")
    result = get_aurora_tip(category, sid)
    if sid: log_aurora_session(sid, category, result["text"])
    audio_bytes = text_to_speech(result["text"], voice="nova")
    audio_b64 = base64.b64encode(audio_bytes).decode() if audio_bytes else ""
    return jsonify({"text": result["text"], "audio_b64": audio_b64})


@app.route("/api/stats/weekly")
def api_weekly_stats():
    from datetime import date, timedelta
    from database import get_weekly_stats
    today = date.today()
    sunday = today - timedelta(days=today.weekday() + 1)
    return jsonify(get_weekly_stats(str(sunday)))


@app.route("/api/stats/today")
def api_today_stats():
    conn = get_db()
    noah = conn.execute("""
        SELECT COUNT(DISTINCT s.id) as sessions, COUNT(wa.id) as attempts,
               COALESCE(SUM(wa.correct),0) as correct
        FROM sessions s LEFT JOIN word_attempts wa ON wa.session_id=s.id
        WHERE s.profile_id=(SELECT id FROM profiles WHERE type='noah')
          AND DATE(s.started_at)=DATE('now','localtime')
    """).fetchone()
    cost = conn.execute("""
        SELECT COALESCE(SUM(cost_usd),0) as total FROM api_usage
        WHERE DATE(created_at)=DATE('now','localtime')
    """).fetchone()
    conn.close()
    return jsonify({"noah_sessions": noah["sessions"], "noah_attempts": noah["attempts"],
                    "noah_correct": noah["correct"], "cost_usd_today": round(cost["total"], 4)})


@app.route("/api/wake", methods=["POST"])
def api_wake(): return jsonify({"status": "awake"})


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    ssl_cert = os.environ.get("SSL_CERT")
    ssl_key = os.environ.get("SSL_KEY")
    logger.info(f"[App] Iniciando na porta {port}")
    if ssl_cert and ssl_key:
        app.run(host="0.0.0.0", port=port, debug=False, ssl_context=(ssl_cert, ssl_key))
    else:
        app.run(host="0.0.0.0", port=port, debug=False)
