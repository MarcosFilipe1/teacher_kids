"""
cron_report.py — Executado todo domingo às 8h pelo OpenClaw ou cron do sistema.

Crontab: 0 8 * * 0 /usr/bin/python3 /home/pi/eduapp/cron_report.py

O OpenClaw chama este script via skill ou via agendamento interno.
"""

import os
import sys
import json
import logging
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(__file__))

from database import get_weekly_stats, get_db
from teacher import generate_weekly_summary

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

USD_TO_BRL = float(os.environ.get("USD_TO_BRL", "5.20"))


def format_whatsapp_report(stats: dict, summary: str) -> str:
    """Formata o relatório para envio via WhatsApp (texto plano com emojis)."""

    noah = stats["noah"]
    aurora = stats["aurora"]
    cost_usd = stats["cost_usd"]
    cost_brl = cost_usd * USD_TO_BRL
    cost_per_session = (cost_brl / noah["sessions"]) if noah["sessions"] > 0 else 0

    # Palavras mais difíceis
    hardest = noah.get("hardest_words", [])
    hardest_str = ", ".join([f"{w['word_pt']}/{w['word_en']}" for w in hardest[:3]]) or "nenhuma"

    # Semana
    week_start = stats["week_start"]

    lines = [
        f"📊 *Relatório semanal — {week_start}*",
        "",
        f"👦 *Noah (6 anos)*",
        f"• {noah['sessions']} sessões · {noah['minutes']} min no total",
        f"• {noah['words_practiced']} palavras praticadas",
        f"• {noah['accuracy_pct']}% de acerto",
    ]

    if hardest:
        lines.append(f"• Mais difíceis: {hardest_str}")

    lines += [
        "",
        f"👶 *Aurora (10 meses)*",
        f"• {aurora['sessions']} sessões de estimulação",
    ]

    if aurora["categories"]:
        cats = aurora["categories"].replace(",", ", ")
        lines.append(f"• Categorias usadas: {cats}")

    lines += [
        "",
        f"💰 *Custo da semana*",
        f"• Total: U${cost_usd:.3f} · R${cost_brl:.2f}",
    ]

    if noah["sessions"] > 0:
        lines.append(f"• Por sessão: R${cost_per_session:.2f}")

    if summary:
        lines += ["", f"💡 *Análise da Luna*", summary]

    lines += [
        "",
        "_Gerado automaticamente — EduApp 🎓_",
    ]

    return "\n".join(lines)


def save_report(stats: dict, text: str):
    """Salva relatório no banco de dados."""
    conn = get_db()
    conn.execute("""
        INSERT INTO weekly_reports
        (week_start, noah_sessions, noah_minutes, noah_words_practiced,
         noah_words_correct, noah_hardest_words, aurora_sessions, aurora_categories,
         total_cost_usd, summary_text, sent_at)
        VALUES (?,?,?,?,?,?,?,?,?,?, CURRENT_TIMESTAMP)
    """, (
        stats["week_start"],
        stats["noah"]["sessions"],
        stats["noah"]["minutes"],
        stats["noah"]["words_practiced"],
        stats["noah"]["words_correct"],
        json.dumps([w["word_pt"] for w in stats["noah"]["hardest_words"]]),
        stats["aurora"]["sessions"],
        stats["aurora"]["categories"],
        stats["cost_usd"],
        text,
    ))
    conn.commit()
    conn.close()


def run_weekly_report(week_start: str = None) -> str:
    """
    Gera e retorna o texto do relatório semanal.
    Se week_start não for informado, usa o domingo anterior.
    """
    if not week_start:
        today = date.today()
        last_sunday = today - timedelta(days=today.weekday() + 1)
        week_start = str(last_sunday)

    logger.info(f"[Cron] Gerando relatório para semana {week_start}")

    stats = get_weekly_stats(week_start)
    logger.info(f"[Cron] Stats coletadas: {stats}")

    summary = generate_weekly_summary(stats)
    report_text = format_whatsapp_report(stats, summary)

    save_report(stats, summary)
    logger.info("[Cron] Relatório salvo no banco")

    return report_text


if __name__ == "__main__":
    # Quando chamado diretamente, imprime o relatório
    # O OpenClaw lê o stdout e envia via WhatsApp
    week = sys.argv[1] if len(sys.argv) > 1 else None
    report = run_weekly_report(week)
    print(report)
