import os
import logging
import httpx
from database import log_api_usage

logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MODEL = "claude-haiku-4-5"

LUNA_PERSONA = """Você é a Professora Luna, uma professora MUITO animada, carinhosa e divertida.
Você ensina crianças de 6 anos a falar português e inglês.

REGRAS ABSOLUTAS:
- Frases CURTAS. Máximo 2-3 frases por resposta.
- Linguagem simples, de criança de 6 anos.
- Sempre animada e encorajadora.
- Nunca critique — só elogie e corrija com carinho.
- Misture PT e EN naturalmente.
- Pronúncia fonética entre parênteses: dog (dóg).

VOCÊ É A PROFESSORA — você comanda a aula:
- Apresente palavras com entusiasmo
- Peça para repetir de forma animada
- Dê feedback imediato e positivo
- Decida sozinha quando avançar ou reforçar

ADAPTAÇÃO AUTOMÁTICA:
- Acertou 2x seguidas → elogie muito, use [PRÓXIMA]
- Errou 2x seguidas → simplifique, quebre em sílabas
- Errou 3x → dê a resposta, elogie, use [PRÓXIMA]
- Completou todas as palavras → use [COMPLETO]

AÇÕES (inclua no fim quando necessário):
[PRÓXIMA] = avança para próxima palavra
[REPETIR] = repete a mesma palavra
[COMPLETO] = step terminado, parabéns!
[SIMPLIFICAR] = reduz dificuldade
"""

ACTIVITY_INTROS = {
    "words_animals":  "Atividade: ANIMAIS bilíngue. Palavras: {words}. Apresente a PRIMEIRA com emoji e entusiasmo. Diga PT e EN. Peça para repetir em inglês.",
    "words_fruits":   "Atividade: FRUTAS bilíngue. Palavras: {words}. Apresente a PRIMEIRA fruta. Diga PT e EN. Peça para repetir.",
    "words_colors":   "Atividade: CORES bilíngue. Palavras: {words}. Comece com a PRIMEIRA cor. PT e EN. Peça para repetir.",
    "letters":        "Atividade: LETRAS e SONS. Letras: {words}. Ensine o som da primeira letra em PT e EN.",
    "syllables":      "Atividade: SÍLABAS. Palavras: {words}. Divida a primeira palavra em sílabas batendo palmas.",
    "story":          "Atividade: FRASES SIMPLES. Frases: {words}. Ensine a primeira frase em PT e EN devagar.",
}


def _call_claude(messages: list, system: str, session_id: int = None) -> dict:
    try:
        response = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={"model": MODEL, "max_tokens": 200, "system": system, "messages": messages},
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()
        text = data["content"][0]["text"]
        tokens_in = data["usage"]["input_tokens"]
        tokens_out = data["usage"]["output_tokens"]
        cost = (tokens_in * 0.0000008) + (tokens_out * 0.000004)
        if session_id:
            log_api_usage(session_id, "claude", tokens_in, tokens_out, cost)
        return {"text": text, "tokens_in": tokens_in, "tokens_out": tokens_out, "cost_usd": round(cost, 6)}
    except Exception as e:
        logger.error(f"[Luna] Erro API: {e}")
        return {"text": "Ops! Vamos tentar de novo?", "tokens_in": 0, "tokens_out": 0, "cost_usd": 0}


def parse_action(text: str) -> tuple:
    """Extrai ação da resposta. Retorna (texto_limpo, ação)."""
    for tag in ["[PRÓXIMA]", "[REPETIR]", "[COMPLETO]", "[SIMPLIFICAR]"]:
        if tag in text:
            return text.replace(tag, "").strip(), tag.strip("[]")
    return text, None


def luna_start_activity(activity_type: str, word_set: list, session_id: int = None) -> dict:
    """Luna fala ao abrir a atividade — apresenta o tema e a primeira palavra."""
    words_str = ", ".join([f"{w['pt']}={w['en']}" for w in word_set[:5]])
    ctx_key = activity_type if activity_type in ACTIVITY_INTROS else "words_animals"
    context = ACTIVITY_INTROS[ctx_key].format(words=words_str)
    system = f"{LUNA_PERSONA}\n\n{context}"
    result = _call_claude([{"role": "user", "content": "Começar aula."}], system, session_id)
    clean, action = parse_action(result["text"])
    result["text"] = clean
    result["action"] = action
    return result


def luna_respond(
    child_said: str,
    activity_type: str,
    current_word: dict,
    correct: bool,
    attempts: int,
    consecutive_correct: int,
    consecutive_errors: int,
    conversation_history: list,
    session_id: int = None,
) -> dict:
    """Luna responde ao Noah e decide o próximo passo automaticamente."""
    context = f"""Aula atual:
- Palavra: {current_word.get('pt','')} = {current_word.get('en','')} {current_word.get('ph','')}
- Noah disse: "{child_said}" | Correto: {correct}
- Tentativas: {attempts} | Acertos seguidos: {consecutive_correct} | Erros seguidos: {consecutive_errors}
Responda com feedback e use a ação correta no fim."""

    system = f"{LUNA_PERSONA}\n\n{context}"
    history = (conversation_history[-6:] if conversation_history else [])
    history.append({"role": "user", "content": f'Noah disse: "{child_said}"'})

    result = _call_claude(history, system, session_id)
    clean, action = parse_action(result["text"])

    # Auto-decide se Luna não incluiu ação
    if not action:
        if consecutive_errors >= 3 or consecutive_correct >= 2:
            action = "PRÓXIMA"

    result["text"] = clean
    result["action"] = action
    return result


def luna_free_talk(
    child_said: str,
    activity_type: str,
    current_word: dict,
    conversation_history: list,
    session_id: int = None,
) -> dict:
    """Noah falou algo livre — não foi tentativa de palavra. Luna responde e volta à aula."""
    context = f"""Aula de {activity_type}. Palavra atual: {current_word.get('pt','')} = {current_word.get('en','')}.
Noah disse algo livre: "{child_said}". Responda, ajude se necessário, e volte à aula."""
    system = f"{LUNA_PERSONA}\n\n{context}"
    history = (conversation_history[-4:] if conversation_history else [])
    history.append({"role": "user", "content": child_said})
    result = _call_claude(history, system, session_id)
    clean, action = parse_action(result["text"])
    result["text"] = clean
    result["action"] = action
    return result


def get_aurora_tip(category: str, session_id: int = None) -> dict:
    system = f"""{LUNA_PERSONA}
Agora dê dicas para PAIS estimularem linguagem de bebê de 10 meses.
Seja prática. Inclua exemplo de frase bilíngue PT/EN para usar com o bebê."""
    messages = [{"role": "user", "content":
        f"Dica prática para estimular linguagem bilíngue de bebê 10 meses. Categoria: {category}."}]
    return _call_claude(messages, system, session_id)


def generate_weekly_summary(stats: dict) -> str:
    system = f"""{LUNA_PERSONA}
Escreva relatório semanal para o PAI. Positivo, mostre progresso, 1 sugestão.
Máximo 4 frases. Só o texto, sem título."""
    prompt = f"""Semana: Noah fez {stats['noah']['sessions']} sessões, {stats['noah']['minutes']} min,
{stats['noah']['words_practiced']} palavras, {stats['noah']['accuracy_pct']}% acerto.
Difíceis: {', '.join([w['word_pt'] for w in stats['noah']['hardest_words'][:3]])}.
Aurora: {stats['aurora']['sessions']} sessões. Custo: U${stats['cost_usd']}"""
    result = _call_claude([{"role": "user", "content": prompt}], system)
    return result["text"]


# Compatibilidade com código antigo
def ask_teacher(user_message, activity_type="words", session_id=None, conversation_history=None):
    if conversation_history is None:
        conversation_history = []
    system = f"{LUNA_PERSONA}\nContexto: {activity_type}"
    history = conversation_history[-6:]
    history.append({"role": "user", "content": user_message})
    return _call_claude(history, system, session_id)

def get_word_feedback(word_pt, word_en, child_said, correct):
    return luna_respond(
        child_said=child_said, activity_type="words_animals",
        current_word={"pt": word_pt, "en": word_en},
        correct=correct, attempts=1,
        consecutive_correct=1 if correct else 0,
        consecutive_errors=0 if correct else 1,
        conversation_history=[],
    )
