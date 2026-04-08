import os
import json
import logging
from flask import Flask, request, jsonify, render_template, send_file
from database import (
    init_db, get_db, start_session, end_session,
    log_word_attempt, log_aurora_session, log_api_usage
)
from teacher import ask_teacher, get_word_feedback, get_aurora_tip
from voice import text_to_speech, speech_to_text, tts_cached, estimate_tts_cost

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "eduapp-secret-2025")

# Estado em memória das sessões ativas (session_id por perfil)
active_sessions = {}
conversation_histories = {}

# ─── Páginas ──────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/noah")
def noah():
    return render_template("noah.html")


@app.route("/aurora")
def aurora():
    return render_template("aurora.html")


# ─── API: Sessões ─────────────────────────────────────────────────────────────

@app.route("/api/session/start", methods=["POST"])
def api_start_session():
    data = request.json
    profile_type = data.get("profile")  # 'noah' ou 'aurora'
    activity = data.get("activity", "words")

    conn = get_db()
    profile = conn.execute(
        "SELECT id FROM profiles WHERE type = ?", (profile_type,)
    ).fetchone()
    conn.close()

    if not profile:
        return jsonify({"error": "Perfil não encontrado"}), 404

    session_id = start_session(profile["id"], activity)
    active_sessions[profile_type] = session_id
    conversation_histories[session_id] = []

    logger.info(f"[Session] Iniciada: {profile_type} / {activity} / id={session_id}")
    return jsonify({"session_id": session_id})


@app.route("/api/session/end", methods=["POST"])
def api_end_session():
    data = request.json
    profile_type = data.get("profile")
    session_id = active_sessions.get(profile_type)
    if session_id:
        end_session(session_id)
        conversation_histories.pop(session_id, None)
        active_sessions.pop(profile_type, None)
    return jsonify({"ok": True})


# ─── API: Interação de voz ────────────────────────────────────────────────────

@app.route("/api/voice/listen", methods=["POST"])
def api_voice_listen():
    """Recebe áudio do browser, transcreve com Whisper, retorna texto."""
    if "audio" not in request.files:
        return jsonify({"error": "Nenhum áudio enviado"}), 400

    audio_bytes = request.files["audio"].read()
    text = speech_to_text(audio_bytes, language="pt")
    return jsonify({"text": text})


@app.route("/api/voice/respond", methods=["POST"])
def api_voice_respond():
    """
    Recebe texto do Noah, manda para a Professora Luna,
    retorna resposta em texto + áudio base64.
    """
    data = request.json
    profile_type = data.get("profile", "noah")
    user_text = data.get("text", "")
    activity = data.get("activity", "words")

    session_id = active_sessions.get(profile_type)
    history = conversation_histories.get(session_id, [])

    result = ask_teacher(
        user_text,
        activity_type=activity,
        session_id=session_id,
        conversation_history=history,
    )

    # Atualiza histórico
    history.append({"role": "user", "content": user_text})
    history.append({"role": "assistant", "content": result["text"]})
    if session_id:
        conversation_histories[session_id] = history[-10:]

    # Gera áudio da resposta
    audio_bytes = text_to_speech(result["text"], voice="nova")
    audio_b64 = ""
    if audio_bytes:
        import base64
        audio_b64 = base64.b64encode(audio_bytes).decode()

        # Registra custo do TTS
        if session_id:
            tts_cost = estimate_tts_cost(result["text"])
            log_api_usage(session_id, "openai_tts", 0, 0, tts_cost)

    return jsonify({
        "text": result["text"],
        "audio_b64": audio_b64,
        "cost_usd": result["cost_usd"],
    })


# ─── API: Atividade de palavras ───────────────────────────────────────────────

@app.route("/api/word/feedback", methods=["POST"])
def api_word_feedback():
    """Feedback da professora após Noah tentar pronunciar uma palavra."""
    data = request.json
    word_pt = data.get("word_pt", "")
    word_en = data.get("word_en", "")
    child_said = data.get("child_said", "")
    correct = data.get("correct", False)
    session_id = active_sessions.get("noah")

    result = get_word_feedback(word_pt, word_en, child_said, correct)

    if session_id:
        log_word_attempt(session_id, word_pt, word_en, correct)

    audio_bytes = text_to_speech(result["text"], voice="nova")
    audio_b64 = ""
    if audio_bytes:
        import base64
        audio_b64 = base64.b64encode(audio_bytes).decode()

    return jsonify({
        "text": result["text"],
        "audio_b64": audio_b64,
        "correct": correct,
    })


# ─── API: Aurora ──────────────────────────────────────────────────────────────

@app.route("/api/aurora/tip", methods=["POST"])
def api_aurora_tip():
    """Dica de estimulação para Aurora."""
    data = request.json
    category = data.get("category", "sons")
    session_id = active_sessions.get("aurora")

    result = get_aurora_tip(category)

    if session_id:
        log_aurora_session(session_id, category, result["text"])

    audio_bytes = text_to_speech(result["text"], voice="nova")
    audio_b64 = ""
    if audio_bytes:
        import base64
        audio_b64 = base64.b64encode(audio_bytes).decode()

    return jsonify({
        "text": result["text"],
        "audio_b64": audio_b64,
    })


# ─── API: Wake word simulado (fallback sem mic físico) ────────────────────────

@app.route("/api/wake", methods=["POST"])
def api_wake():
    """Endpoint para simular wake word via toque na tela ou botão físico."""
    return jsonify({"status": "awake", "message": "Pronta para ouvir!"})


# ─── API: Stats para OpenClaw ────────────────────────────────────────────────

@app.route("/api/stats/weekly")
def api_weekly_stats():
    """Retorna stats da semana atual em JSON — consumido pelo OpenClaw."""
    from datetime import date, timedelta
    from database import get_weekly_stats

    today = date.today()
    sunday = today - timedelta(days=today.weekday() + 1)
    stats = get_weekly_stats(str(sunday))
    return jsonify(stats)


@app.route("/api/stats/today")
def api_today_stats():
    """Stats rápidas do dia — para OpenClaw responder perguntas pontuais."""
    conn = get_db()
    noah_today = conn.execute("""
        SELECT COUNT(DISTINCT s.id) as sessions, COUNT(wa.id) as attempts,
               COALESCE(SUM(wa.correct),0) as correct
        FROM sessions s
        LEFT JOIN word_attempts wa ON wa.session_id = s.id
        WHERE s.profile_id = (SELECT id FROM profiles WHERE type='noah')
          AND DATE(s.started_at) = DATE('now','localtime')
    """).fetchone()

    cost_today = conn.execute("""
        SELECT COALESCE(SUM(cost_usd),0) as total
        FROM api_usage
        WHERE DATE(created_at) = DATE('now','localtime')
    """).fetchone()

    conn.close()
    return jsonify({
        "noah_sessions": noah_today["sessions"],
        "noah_attempts": noah_today["attempts"],
        "noah_correct": noah_today["correct"],
        "cost_usd_today": round(cost_today["total"], 4),
    })


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    logger.info(f"[App] Iniciando na porta {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
