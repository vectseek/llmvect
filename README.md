<div align="center">

# ⚡ LLMVECT

**The open-source arena for evaluating large language models.**

Blind A/B testing. Statistical ranking. 139 models. Zero bias.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)

[Getting Started](#-quick-start) · [Architecture](#-architecture) · [Contributing](#-contributing) · [License](#license)

</div>

---

## Why LLMVECT?

Model benchmarks are gamed. Leaderboards are static. Chatbot comparisons are subjective.

LLMVECT fixes this with **blind arena battles** — you compare two model responses side-by-side without knowing which model produced them. Your votes feed into a **Plackett-Luce ranking engine** with UCB-E uncertainty modeling, producing statistically rigorous, continuously updated rankings.

No cherry-picked benchmarks. No marketing scores. Just real human preference.

## Features

| | Feature | Description |
|---|---------|-------------|
| 🎯 | **Blind Arena** | Side-by-side model comparison with hidden identities until vote |
| 📊 | **Statistical Ranking** | Plackett-Luce + UCB-E Thompson Sampling — mathematically rigorous |
| 🌍 | **139 Models** | 88 Chinese + 51 global models across 30+ providers |
| ⚡ | **Dual Mode** | Fast mode (2-model duel) and Expert mode (4-model battle royale) |
| 🛡️ | **Anti-Cheat** | Browser fingerprinting, rate limiting, and vote weight auditing |
| 🔑 | **Sponsor System** | Community-driven — contribute API keys to unlock new models |
| 🌐 | **i18n** | English + Chinese with automatic language detection |

## Quick Start

```bash
git clone https://github.com/vectseek/llmvect.git
cd llmvect

python3 -m venv backend/venv
source backend/venv/bin/activate   # Windows: backend\venv\Scripts\activate
pip install -r backend/requirements.txt

cd backend
uvicorn main:app --host 127.0.0.1 --port 8001
```

Open **http://127.0.0.1:8001** — you're live.

### Configuration

```bash
cp .env.example .env
```

| Variable | Required | Description |
|----------|----------|-------------|
| `ADMIN_PASSWORD` | No | Admin login password. Auto-generated if unset (printed to console on first run) |
| `DASHSCOPE_API_KEY` | No | Alibaba Qwen |
| `OPENAI_API_KEY` | No | OpenAI GPT |
| `ANTHROPIC_API_KEY` | No | Claude |
| `GOOGLE_API_KEY` | No | Gemini |
| ... | ... | See [.env.example](.env.example) for all 37 providers |

API keys can also be configured via the admin panel at `/admin.html`.

## Architecture

```
llmvect/
├── backend/
│   ├── main.py            FastAPI application & arena endpoints
│   ├── models.py          139 model definitions across 37 providers
│   ├── lobster.py         Plackett-Luce + UCB-E ranking engine
│   ├── auto_router.py     Intelligent model routing & failover
│   ├── fingerprint.py     Browser fingerprint anti-cheat
│   ├── quota.py           Rate limiting & quota tracking
│   ├── sponsor_api.py     Community API key contribution
│   ├── totoro.py          Turing test / verification
│   ├── category.py        Model categorization logic
│   └── check_db.py        Database health checks
├── frontend/
│   ├── index.html         Arena — the main event
│   ├── leaderboard.html   Live rankings
│   ├── sponsor.html       Contribute API keys
│   ├── rules.html         Arena rules & FAQ
│   └── protocol.html      Privacy & terms
├── deploy.sh              One-command deployment
├── requirements.txt       Python dependencies
└── .env.example           Environment variable template
```

## Tech Stack

| Layer | Choice | Why |
|-------|--------|-----|
| Backend | **FastAPI** | Async-first, automatic OpenAPI docs, production-ready |
| Ranking | **Plackett-Luce + UCB-E** | Proven statistical framework with uncertainty bounds |
| Database | **SQLite** | Zero-config, file-based, perfect for single-node deployment |
| Frontend | **Vanilla HTML/CSS/JS** | No build step, no dependencies, instant load |
| Theme | **Obsidian Dark** | Precision-crafted dark UI, easy on the eyes |

## Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

MIT License — see [LICENSE](LICENSE). Use it, modify it, ship it. Just keep the copyright notice.

---

<div align="center">

Built with reference to the open-source model evaluation ecosystem, including [HuggingFace chat-ui](https://github.com/huggingface/chat-ui) and [LMSYS Chatbot Arena](https://chat.lmsys.org).

**[⬆ Back to Top](#-llmvect)**

</div>
