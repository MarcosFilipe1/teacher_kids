# EduApp Parental Control Skill

## Description
Controle parental do EduApp — app educativo bilíngue dos filhos Noah (6 anos) e Aurora (10 meses).
Permite monitorar progresso, consultar custos e acionar o relatório semanal via WhatsApp.

## Base URL
http://localhost:5000

## Available Commands

### Progresso do dia
Trigger: "progresso hoje", "como foi hoje", "noah hoje"
Action: GET /api/stats/today
Response format: "Hoje o Noah fez {sessions} sessões, praticou {attempts} palavras com {pct}% de acerto. Custo do dia: R${cost}."

### Progresso da semana
Trigger: "relatório da semana", "como foi a semana", "progresso semanal"
Action: GET /api/stats/weekly
Response format: Format as a summary message with Noah stats, Aurora stats, and cost breakdown.

### Relatório WhatsApp
Trigger: "gera relatório", "manda relatório", "relatório completo"
Action: Run shell command: python3 /home/pi/eduapp/cron_report.py
Response: Send the output directly as WhatsApp message.

### Custo acumulado
Trigger: "quanto gastei", "custo da api", "custo do mês"
Action: GET /api/stats/weekly
Response format: "Custo da semana: U${cost_usd} (R${cost_brl}). Estimativa mensal: R${monthly}."

### Status do app
Trigger: "app está rodando", "status do app", "eduapp online"
Action: GET /api/stats/today (check if responds)
Response: "EduApp está online ✅" or "EduApp não está respondendo ❌"

## Shell Commands Allowed
- python3 /home/pi/eduapp/cron_report.py          # gera relatório
- python3 /home/pi/eduapp/cron_report.py YYYY-MM-DD  # relatório de semana específica
- systemctl status eduapp                           # verifica status do serviço
- systemctl restart eduapp                          # reinicia se necessário

## Response Language
Always respond in Brazilian Portuguese.

## Security
Only respond to the owner's WhatsApp number. Do not expose API keys or internal paths in responses.
