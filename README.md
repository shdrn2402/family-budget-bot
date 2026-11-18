# 💰 Family Budget Bot

[![CI/CD Pipeline](https://github.com/shdrn2402/family-budget-bot/actions/workflows/deploy.yaml/badge.svg)](https://github.com/shdrn2402/family-budget-bot/actions/workflows/deploy.yaml)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![Package Manager: uv](https://img.shields.io/badge/package--manager-uv-brightgreen)](https://docs.astral.sh/uv/)
[![Database: PostgreSQL 18](https://img.shields.io/badge/database-postgresql--18-blue)](https://www.postgresql.org/)
[![AI: Gemini 1.5 Flash](https://img.shields.io/badge/AI-Gemini%201.5%20Flash-orange)](https://ai.google.dev/)
[![Security: Hardened](https://img.shields.io/badge/DB_Access-Direct%20%2F%20SSH%20Tunnel-informational)](#-tech-stack--port-mapping)
[![Status: In Progress](https://img.shields.io/badge/Status-In%20Progress-yellow)](#-roadmap--backlog)

**Family Budget Bot** is a private, bilingual (English/Russian) Telegram bot designed for family finance tracking. It combines LLM-powered natural language processing, voice transcription, and structured database synchronization.

---

## ⚙️ System Architecture

```mermaid
graph TD
    TelegramUser[Telegram User] <--> |Commands / Text / Voice / Files| Bot[Telegram Budget Bot]
    Bot <--> |Gemini API| Gemini[Google Gemini 1.5 Flash]
    Bot <--> |psycopg3 / Port 5432| DB[(PostgreSQL 18)]
    DBClient[Local Client: DBeaver] -.-> |Direct / SSH Tunnel| DB
    DB -.-> |Automatic db_dump| Backup[./backups/]
    DBTrigger[PostgreSQL Trigger] -.-> |Sync Alias Updates| DB
```

---

## ✨ Core Features

*   🎙 **Voice-to-Text Parsing:** Records expenses from voice messages by transcribing audio via Gemini 1.5 Flash, then maps details into structured transactions (item, account, amount, category).
*   💬 **Smart Natural Language Entry:** Processes free-form text (e.g., *"spent 500 on coffee yesterday in cash and 2k on fuel with credit card"*) to log multiple transactions at once.
*   ⏳ **Debounced Batch Statement Loading:** Groups multiple statement uploads (Excel/XLSX) sent in a single batch, processes them in one operation, and outputs a single aggregated report to avoid message spam.
*   📊 **Bit Statement Import & Reconciliation:** Parses Bit CSV exports, matches/enriches existing bank and credit card statement transactions, and handles direct card expenses and transit balance movements without duplication.
*   🗃 **Database-Level Alias Synchronization:** Uses a PostgreSQL trigger (`trg_update_item_alias`) on transaction category updates. Modifying a transaction's category automatically synchronizes or inserts the corresponding pattern in `item_aliases` to categorize future statements correctly.
*   🤖 **Bilingual Interface:** Supports dynamic runtime localization (English/Russian) through a centralized translation system (`bot/texts.py`).
*   🔒 **Access Control Whitelist:** Restricts access to predefined Telegram User IDs with granular admin flags (`is_admin`).

---

## 🛠 Tech Stack & Port Mapping

| Service | Technology | Port (Host:Container) | Description |
| :--- | :--- | :--- | :--- |
| **Bot Ingestion** | Python 3.12 + `uv` | *N/A (Stateless)* | Telegram webhook/polling daemon |
| **Database** | PostgreSQL 18 | `5433:5432` | Primary transactional storage |
| **DB Administration** | DBeaver / CLI | *Via SSH Tunnel / Host Port* | Direct administration without exposed web GUIs |
| **LLM Engine** | Gemini 1.5 Flash | *API* | Voice transcription and entity extraction |

---

## 🔄 CI/CD & Production Deployment

The project features a fully automated CI/CD pipeline configured via GitHub Actions (`deploy.yaml`).

### Pipeline Stages
1.  **Run Tests:** Automatically provisions a runner, restores dependencies using cached Astral `uv`, and executes unit tests via `pytest`.
2.  **Build and Push:** Compiles the Docker image and pushes it to the GitHub Container Registry (`ghcr.io/shdrn2402/my_family_budget/budget_bot:latest`).
3.  **VPS Deploy:** Connects to the DigitalOcean VPS via SSH:
    *   Creates an automatic pre-deployment database dump inside `./backups/` to prevent data loss.
    *   Regenerates the local `.env` configuration file from GitHub Secrets.
    *   Pulls the updated repository code.
    *   Launches services using `docker compose` in detached mode.

> [!NOTE]
> Pushes containing the tag `[skip ci]` in their commit message bypass the CI/CD pipeline execution.

---

## 🚀 Setup & Local Development

### 1. Configure Environment Variables
Create a `.env` file in the root directory (based on `env.example`):
```env
TELEGRAM_TOKEN="your_telegram_bot_token"
ALLOWED_USER_IDS="your_allowed_telegram_user_ids"
DB_HOST="pgdatabase"
DB_PORT=5432
DB_NAME="your_db_name"
DB_USER="your_db_user"
DB_PASSWORD="your_db_password"
GEMINI_API_KEY="your_gemini_api_key"
```

### 2. Running Locally with Docker
Ensure Docker and Compose are installed, then run:
```bash
docker compose up -d --build
```
On startup, the bot brings the database schema up to date with [Alembic](https://alembic.sqlalchemy.org/) migrations (`migrations/`):
*   **Empty database:** creates the schema, then loads the reference data from `scripts/seed_data.sql`.
*   **Existing database created before migrations were introduced:** marks it as the baseline revision without changing it, then applies newer migrations.
*   **Already migrated:** applies any new migrations.
*   **Incomplete schema:** refuses to start. Nothing is ever dropped automatically.

To change the schema, add a new revision (`uv run alembic revision -m "describe the change"`) instead of editing existing ones.

### 3. Running Locally without Docker (for debugging)
Install Astral `uv` and run:
```bash
uv sync
uv run pytest     # Run tests
uv run main.py    # Start the bot
```

Integration tests (`tests/integration/`) run against a real PostgreSQL and are skipped unless `TEST_DATABASE_URL` is set:
```bash
docker run --rm -d --name budget-test-pg -p 127.0.0.1:55432:5432 -e POSTGRES_PASSWORD=postgres postgres:18
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:55432/postgres uv run pytest
```

### 4. Restoring a Backup
Restoring is a manual, explicit operation. Get a backup (for example from the bot's `/backup` command, or a pre-deploy `backup_before_deploy_*.dump` on the server), then run from the directory containing `compose.yaml`:
```bash
./scripts/restore_db.sh path/to/backup.sql   # or .dump
```
The script asks you to type the database name, stops the bot, replaces the `budget` schema with the backup, and starts the bot again; the bot then applies any missing migrations. Plain `.sql` backups are restored in a single transaction, so a failed restore changes nothing.

---

## 📅 Roadmap & Backlog
*   Check [ROADMAP.md](./docs/ROADMAP.md) for completed phases and upcoming ergonomic improvements.
*   Check [BACKLOG.md](./docs/BACKLOG.md) for future project architecture ideas.
