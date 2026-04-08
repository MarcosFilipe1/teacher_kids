import os
import json
import logging
import httpx
from database import log_api_usage

logger = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MODEL = "claude-haiku-4-5-20251001"  # mais barato, rápido para crianças

SYSTEM_PROMPT = """Você é a Professora Luna, uma professora animada, carinhosa e divertida que ensina crianças pequenas.

Seu aluno principal é Noah, 6 anos, que está aprendendo a ler em português e está começando o inglês do zero.

Regras IMPORTANTES:
- Fale de forma simples, com frases curtas e alegres
- Misture português e inglês naturalmente: diga a palavra em PT, depois em EN com entusiasmo
- Use muito encorajamento: "Que incrível!", "Você arrasou!", "Muito bem!", "Parabéns!"
- Quando Noah errar, seja gentil: "Quase lá! Vamos tentar juntos?"
- Nunca use palavras difíceis ou explicações longas
- Máximo 2-3 frases por resposta — crianças não têm paciência para textos longos
- Pronuncie as palavras em inglês de forma fonética entre parênteses quando necessário
- Exemplo: "Gato em inglês é CAT (cat)! Repita comigo: cat, cat, cat!"

Para a Aurora (10 meses), você dá dicas aos pais sobre estimulação de linguagem."""

ACTIVITY_CONTEXTS = {
    "words": "Estamos na atividade de palavras com figuras. Mostre a palavra, diga em PT e EN, peça para repetir.",
    "letters": "Estamos na atividade de letras e sons. Foque nos sons das letras de forma lúdica.",
    "syllables": "Estamos na atividade de sílabas. Ajude a dividir as palavras em pedacinhos.",
    "story": "Estamos contando uma historinha bilíngue simples. Use frases curtíssimas.",
    "aurora_stimulation": "Você está dando dicas para os pais estimularem a linguagem de um bebê de 10 meses.",
}


def ask_teacher(
    user_message: str,
    activity_type: str = "words",
    session_id: int = None,
    conversation_history: list = None,
) -> dict:
    """
    Envia mensagem para a Professora Luna e retorna resposta + métricas.
    Retorna: { "text": str, "tokens_in": int, "tokens_out": int, "cost_usd": float }
    """
    if conversation_history is None:
        conversation_history = []

    context = ACTIVITY_CONTEXTS.get(activity_type, "")
    system = f"{SYSTEM_PROMPT}\n\nContexto atual: {context}"

    messages = conversation_history[-6:]  # últimas 3 trocas para contexto
    messages.append({"role": "user", "content": user_message})

    try:
        response = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": MODEL,
                "max_tokens": 256,
                "system": system,
                "messages": messages,
            },
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()

        text = data["content"][0]["text"]
        tokens_in = data["usage"]["input_tokens"]
        tokens_out = data["usage"]["output_tokens"]

        # Haiku: $0.80/1M input, $4.00/1M output
        cost = (tokens_in * 0.0000008) + (tokens_out * 0.000004)

        if session_id:
            log_api_usage(session_id, "claude", tokens_in, tokens_out, cost)

        return {
            "text": text,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_usd": round(cost, 6),
        }

    except Exception as e:
        logger.error(f"[Teacher] Erro na API Claude: {e}")
        return {
            "text": "Ops! Tive um probleminha. Vamos tentar de novo?",
            "tokens_in": 0,
            "tokens_out": 0,
            "cost_usd": 0,
        }


def get_word_feedback(word_pt: str, word_en: str, child_said: str, correct: bool) -> dict:
    """Feedback específico para tentativa de palavra."""
    if correct:
        msg = f"Noah disse '{child_said}' tentando falar '{word_en}'. Dê um elogio animado e reforce a pronúncia."
    else:
        msg = f"Noah disse '{child_said}' mas a palavra era '{word_en}' ({word_pt}). Encoraje gentilmente e ajude a pronunciar."
    return ask_teacher(msg, activity_type="words")


def get_aurora_tip(category: str) -> dict:
    """Dica de estimulação para Aurora."""
    msg = f"Dê uma dica prática para os pais estimularem a linguagem bilíngue de um bebê de 10 meses. Categoria: {category}. Seja específico e prático."
    return ask_teacher(msg, activity_type="aurora_stimulation")


def generate_weekly_summary(stats: dict) -> str:
    """Gera texto do relatório semanal usando Claude."""
    prompt = f"""Gere um relatório semanal CURTO e animado em português para um pai sobre o progresso dos filhos.

Dados da semana:
- Noah (6 anos): {stats['noah']['sessions']} sessões, {stats['noah']['minutes']} minutos, 
  {stats['noah']['words_practiced']} palavras praticadas, {stats['noah']['accuracy_pct']}% de acerto
  Palavras mais difíceis: {', '.join([w['word_pt'] for w in stats['noah']['hardest_words'][:3]])}
- Aurora (10 meses): {stats['aurora']['sessions']} sessões de estimulação
- Custo total da API: U${stats['cost_usd']}

Formato: 3-4 frases, tom positivo, mencione 1 conquista e 1 sugestão para a próxima semana.
Responda apenas o texto do relatório, sem título."""

    result = ask_teacher(prompt, activity_type="words")
    return result["text"]
