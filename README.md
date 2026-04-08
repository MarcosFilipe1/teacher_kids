# EduApp — Assistente Educativo Bilíngue

App educativo bilíngue para Noah (6 anos) e Aurora (10 meses), rodando no Raspberry Pi 4.
Controle parental via WhatsApp com OpenClaw. Relatório semanal automático.

---

## Estrutura

```
eduapp/
├── app.py              # Flask — servidor principal
├── database.py         # SQLite — banco de dados
├── teacher.py          # Claude API — Professora Luna
├── voice.py            # OpenAI TTS + Whisper STT
├── cron_report.py      # Relatório semanal
├── requirements.txt
├── templates/
│   ├── index.html      # Tela inicial (seleção de perfil)
│   ├── noah.html       # Atividades do Noah
│   └── aurora.html     # Painel da Aurora
├── static/
│   └── sounds/cache/   # Cache de áudios TTS
└── skills/
    └── weekly-report/
        └── SKILL.md    # Skill do OpenClaw
```

---

## Deploy no Raspberry Pi 4

### 1. Instalar dependências

```bash
sudo apt update && sudo apt install -y python3-pip python3-venv

cd /home/pi
git clone <repo> eduapp  # ou copie os arquivos
cd eduapp

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configurar variáveis de ambiente

```bash
nano /home/pi/eduapp/.env
```

```env
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
SECRET_KEY=sua-chave-secreta-aqui
USD_TO_BRL=5.20
DB_PATH=/home/pi/eduapp/eduapp.db
PORT=5000
```

### 3. Inicializar banco de dados

```bash
source venv/bin/activate
python3 -c "from database import init_db; init_db()"
```

### 4. Criar serviço systemd

```bash
sudo nano /etc/systemd/system/eduapp.service
```

```ini
[Unit]
Description=EduApp Educativo Bilíngue
After=network.target

[Service]
User=pi
WorkingDirectory=/home/pi/eduapp
EnvironmentFile=/home/pi/eduapp/.env
ExecStart=/home/pi/eduapp/venv/bin/python3 app.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable eduapp
sudo systemctl start eduapp
sudo systemctl status eduapp
```

### 5. Acessar no browser da TV

Abra o browser no Raspberry Pi (ou qualquer dispositivo na rede):
```
http://localhost:5000
# ou da TV via IP local:
http://192.168.x.x:5000
```

---

## OpenClaw — Controle Parental via WhatsApp

### Instalar OpenClaw no Pi

```bash
# Requer Node.js 22+
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo bash -
sudo apt install -y nodejs

npm install -g openclaw
openclaw onboard --install-daemon
```

### Conectar WhatsApp

```bash
openclaw channels add --channel whatsapp
openclaw channels login --channel whatsapp
# Escaneie o QR Code com seu WhatsApp
```

### Instalar skill do EduApp

```bash
cp -r /home/pi/eduapp/skills/weekly-report ~/.openclaw/skills/
```

### Configurar número autorizado

Edite `~/.openclaw/openclaw.json`:
```json
{
  "channels": {
    "whatsapp": {
      "dmPolicy": "allowlist",
      "allowFrom": ["+55119XXXXXXXX"]
    }
  }
}
```

---

## Relatório Semanal Automático

### Via cron do sistema (todo domingo às 8h)

```bash
crontab -e
```

```
0 8 * * 0 cd /home/pi/eduapp && /home/pi/eduapp/venv/bin/python3 cron_report.py | openclaw send whatsapp +55119XXXXXXXX
```

### Manualmente via WhatsApp

Envie para o seu bot:
- "gera relatório" → relatório completo
- "como foi hoje" → progresso do dia
- "quanto gastei" → custo da API

---

## Microfone USB

Qualquer microfone USB plug-and-play funciona.
Recomendado: microfone de mesa USB (~R$40 no Mercado Livre).

Verifique se foi reconhecido:
```bash
arecord -l
```

---

## Wake Word (opcional)

Para ativar por voz ("Hey Professora"):

```bash
pip install openwakeword pyaudio
```

Por padrão o app usa o modelo "hey_jarvis" como placeholder.
Para criar modelo customizado em português, siga:
https://github.com/dscripka/openWakeWord#training-new-models

---

## Custos estimados (uso leve)

| Serviço | Uso | Custo/mês |
|---------|-----|-----------|
| Claude Haiku | ~500 msgs/semana | ~$2-4 |
| OpenAI TTS-1 | ~10k chars/semana | ~$0.60 |
| OpenAI Whisper | ~30 min áudio/semana | ~$0.72 |
| **Total** | | **~R$18-28/mês** |
