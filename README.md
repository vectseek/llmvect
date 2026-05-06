# LLMVECT - Open-Source AI Model Arena

A global LLM evaluation platform featuring blind A/B testing, Elo-style rankings, and a battle arena for comparing AI models side-by-side.

## Features

- **Blind Arena** — Vote on model responses without knowing which model produced them
- **Plackett-Luce + UCB-E Ranking** — Statistical ranking engine with uncertainty modeling
- **139 Models** — Supports 88 Chinese + 51 global models across 30+ providers
- **Dual Mode** — Fast mode (2 models) and Expert mode (4 models)
- **Anti-cheat** — Browser fingerprinting, rate limiting, and vote weight auditing
- **Sponsor System** — Users can contribute their own API keys to add model support
- **i18n** — English (default) + Chinese, with auto-detection

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11+ / FastAPI |
| Ranking | Plackett-Luce + UCB-E (Thompson Sampling) |
| Database | SQLite |
| Frontend | Vanilla HTML/CSS/JS (dark Obsidian theme) |
| Deployment | Nginx reverse proxy + uvicorn |

## Quick Start

```bash
# Clone
git clone https://github.com/vectseek/llmvect.git
cd llmvect

# Setup
python3 -m venv backend/venv
source backend/venv/bin/activate  # Windows: backend\venv\Scripts\activate
pip install -r requirements.txt

# Run
cd backend
uvicorn main:app --host 127.0.0.1 --port 8001
```

Then open http://127.0.0.1:8001 in your browser.

## Configuration

1. Copy `.env.example` to `.env` and fill in your API keys
2. Set `ADMIN_PASSWORD` for initial admin login, or a random password is generated on first start
3. Login at `/admin.html` to configure models and keys via the admin panel

## Project Structure

```
llmvect/
├── backend/
│   ├── main.py           # FastAPI app, arena endpoints
│   ├── models.py         # Model definitions (139 models)
│   ├── lobster.py        # Plackett-Luce + UCB-E ranking engine
│   ├── auto_router.py    # Intelligent model routing
│   ├── fingerprint.py    # Browser fingerprint anti-cheat
│   ├── quota.py          # Rate limiting & quota tracking
│   ├── sponsor_api.py    # Sponsor key contribution system
│   ├── totoro.py         # CAPTCHA / Turing test
│   ├── category.py       # Model categorization
│   └── check_db.py       # Database health check
├── frontend/
│   ├── index.html        # Arena homepage
│   ├── leaderboard.html  # Model rankings
│   ├── sponsor.html      # Sponsor submission
│   ├── rules.html        # Rules/FAQ
│   └── protocol.html     # Privacy & terms
├── deploy.sh             # Deployment script
├── requirements.txt
└── .env.example
```

## License

MIT License — see [LICENSE](LICENSE) for details.

## Inspired By

Built with reference to the open-source model evaluation ecosystem, including HuggingFace's chat-ui and LMSYS Chatbot Arena.
