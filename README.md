# Ouroboros Backend

The autonomous coding agent that builds Pyth Network mini-games for you.

> Built for the [Pyth Community Hackathon](https://dev-forum.pyth.network/t/pyth-community-hackathon-official-rules/521) (March 4 - April 1, 2026)

## What It Does

Ouroboros is an AI-powered coding agent that takes a game idea described in plain English, then autonomously scaffolds, develops, and deploys a working mini-game powered by **Pyth Price Feeds** and **Pyth Entropy** (on-chain verifiable randomness). The agent writes code, executes terminal commands, deploys smart contracts to Base Sepolia, and ships frontends to Netlify — all in real time through a chat interface.

Users don't need to know Solidity, React, or how Pyth works. They describe what they want, and Ouroboros builds it.

## Pyth Features Used

- **Price Feeds (Hermes API)** — Real-time asset prices via `hermes.pyth.network`, powering prediction games, trading simulators, and price-reactive gameplay
- **Entropy** — On-chain verifiable randomness on Base Sepolia (`0x4821932D0CDd71225A6d914706A621e0389D7061`), used for dice rolls, loot drops, card games, and fair outcomes
- **MCP Server** — Feed discovery, candlestick data, and historical prices via `mcp.pyth.network` (used by the agent and deployed frontends for richer data queries)

## Architecture

```
Frontend (Nuxt 3)  ──WebSocket──>  Backend (FastAPI)  ──>  LLM (Claude / GPT)
         │                              │                         │
         │                              ├── MongoDB Atlas          │
         │                              ├── Tool Registry ────────┘
         │                              │     ├── File Ops (read, write, patch, search)
         │                              │     ├── Terminal (shell via WSL on Windows)
         │                              │     ├── Pyth Price / Search / Candles / History
         │                              │     └── Pyth Deploy (Foundry → Base Sepolia)
         │                              │
         └── Live Preview ──────────────└── Netlify (deployed games)
```

### Core Modules

| Module | Purpose |
|--------|---------|
| `api/` | FastAPI REST API + WebSocket agent endpoint |
| `core/agent.py` | ReAct agent loop with streaming events (25 iteration budget) |
| `core/prompt.py` | System prompt builder — agent identity, tool guidance, Pyth instructions |
| `core/adapters/` | LLM adapters for Anthropic (Claude) and OpenAI (GPT) |
| `db/` | MongoDB session persistence with cost tracking |
| `tools/` | 10 agent tools — file ops, terminal, and 5 Pyth-specific tools |
| `deploy/` | Production deployment (nginx, systemd, setup script) |

### Agent Tools

| Tool | Description |
|------|-------------|
| `read_file` | Read files with line-by-line pagination |
| `write_file` | Create/overwrite files, auto-creates directories |
| `patch` | Targeted find-and-replace edits |
| `search_files` | Regex content search and glob file search |
| `terminal` | Execute shell commands with streaming output |
| `pyth_price` | Fetch real-time prices from Hermes (BTC, ETH, SOL, and more) |
| `pyth_search` | Discover available price feeds via MCP |
| `pyth_candles` | OHLC candlestick data (1min to monthly) |
| `pyth_history` | Historical prices at specific timestamps |
| `pyth_deploy` | Compile and deploy Solidity contracts to Base Sepolia with Foundry |

## Tech Stack

- **Framework:** FastAPI + Uvicorn (async Python)
- **Database:** MongoDB Atlas via Motor (async driver)
- **LLMs:** Anthropic Claude / OpenAI GPT (user-selectable)
- **Smart Contracts:** Solidity + Foundry, deployed to Base Sepolia
- **Frontend Deploys:** Netlify (automated via API)
- **Pyth Integration:** Hermes REST API + MCP Server

## Setup

### Prerequisites

- Python 3.11+
- MongoDB Atlas account (or local MongoDB)
- Anthropic and/or OpenAI API key

### Install

```bash
git clone https://github.com/anthropics/ouroboros-backend.git
cd ouroboros-backend
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install -r requirements.txt
```

### Configure

Copy `.env.example` to `.env` and fill in your values:

```bash
cp .env.example .env
```

Required variables:
- `MONGODB_URI` — MongoDB connection string
- `ANTHROPIC_API_KEY` and/or `OPENAI_API_KEY` — LLM provider keys
- `CORS_ORIGINS` — Frontend URL(s) for CORS

Optional (for smart contract deployment):
- `BASE_SEPOLIA_RPC` — Base Sepolia RPC endpoint
- `DEPLOYER_PRIVATE_KEY` — Wallet key for contract deployment
- `NETLIFY_AUTH_TOKEN` / `NETLIFY_ACCOUNT_SLUG` — For auto-deploying frontends

### Run

```bash
uvicorn api.main:app --reload --host 0.0.0.0 --port 8001
```

The API is available at `http://localhost:8001` with docs at `/docs`.

### Test

```bash
pytest
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/models` | List available LLM models |
| `GET` | `/api/projects` | List all projects |
| `POST` | `/api/projects` | Create project from template |
| `DELETE` | `/api/projects/{id}` | Delete a project |
| `GET` | `/api/sessions` | List sessions for a project |
| `GET` | `/api/files/{path}` | View file contents |
| `GET` | `/api/admin/stats` | Global usage stats |
| `WS` | `/api/agent` | WebSocket — main agent chat |

## Deployment

Production setup for Ubuntu 22.04+ VPS:

```bash
bash deploy/setup.sh
```

This installs dependencies, creates a Python venv, configures systemd, and sets up nginx with SSL. See `deploy/` for individual config files.

## License

Apache 2.0