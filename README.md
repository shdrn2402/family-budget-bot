# 💰 Family Budget Bot

[![CI/CD Pipeline](https://github.com/shdrn2402/family-budget-bot/actions/workflows/deploy.yaml/badge.svg)](https://github.com/shdrn2402/family-budget-bot/actions/workflows/deploy.yaml)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![Package Manager: uv](https://img.shields.io/badge/package--manager-uv-brightgreen)](https://docs.astral.sh/uv/)
[![Database: PostgreSQL 18](https://img.shields.io/badge/database-postgresql--18-blue)](https://www.postgresql.org/)
[![Security: Hardened](https://img.shields.io/badge/DB_Access-Direct%20%2F%20SSH%20Tunnel-informational)](#-tech-stack--port-mapping)
[![Status: In Progress](https://img.shields.io/badge/Status-In%20Progress-yellow)](#-roadmap--backlog)

**Family Budget Bot** is a private, bilingual (English/Russian) Telegram bot designed for family finance tracking. It records expenses from short text messages and imports bank, credit card and Bit statements into PostgreSQL, reconciling them with what was entered by hand.

---

## ⚙️ System Architecture

```mermaid
graph TD
    TelegramUser[Telegram User] <--> |Commands / Text / Files| Bot[Telegram Budget Bot]
    Bot <--> |psycopg3 / Port 5432| DB[(PostgreSQL 18)]
    DBClient[Local Client: DBeaver] -.-> |Direct / SSH Tunnel| DB
    DB -.-> |Automatic db_dump| Backup[./backups/]
```

---

## ✨ Core Features

*   💬 **Quick Text Entry:** One message can log several expenses in the format `item account amount [comment]`, separated by commas (e.g. *"coffee cash 15, bus card 6 yesterday"*). Account words are aliases from `account_aliases`; *"yesterday"/"today"* set the date. If any part can't be read, nothing is saved and the bot replies with the expected format.
*   ⏳ **Debounced Batch Statement Loading:** Groups multiple statement uploads (Excel/XLSX) sent in a single batch, processes them in one operation, and outputs a single aggregated report to avoid message spam.
*   📊 **Bit Statement Import & Reconciliation:** Parses Bit CSV exports, matches/enriches existing bank and credit card statement transactions, and handles direct card expenses and transit balance movements without duplication.
*   🗃 **Alias Learning:** Changing a transaction's category from the bot's menu saves the merchant pattern (description + comment) to `item_aliases` and applies it to matching uncategorized transactions, so future statements are categorized automatically.
*   🤖 **Bilingual Interface:** Supports dynamic runtime localization (English/Russian) through a centralized translation system (`bot/texts.py`).
*   🔒 **Access Control Whitelist:** Restricts access to predefined Telegram User IDs with granular admin flags (`is_admin`).

---

## 🛠 Tech Stack & Port Mapping

| Service | Technology | Port (Host:Container) | Description |
| :--- | :--- | :--- | :--- |
| **Bot Ingestion** | Python 3.12 + `uv` | *N/A (Stateless)* | Telegram webhook/polling daemon |
| **Database** | PostgreSQL 18 | `5433:5432` | Primary transactional storage |
| **DB Administration** | DBeaver / CLI | *Via SSH Tunnel / Host Port* | Direct administration without exposed web GUIs |

---

## 🔄 CI/CD & Production Deployment

The project features a fully automated CI/CD pipeline configured via GitHub Actions (`deploy.yaml`).

### When It Runs
*   **Pull requests to `main`:** only **Run Tests**. The result is shown on the PR, and a PR must pass it before merging. No image is built and nothing is deployed.
*   **Pushes to `main`** (i.e. merged PRs): all three stages below.
*   A newer commit on the same PR cancels that PR's outdated run. Runs on `main` are never cancelled, so a deploy is never interrupted.

### Pipeline Stages
1.  **Run Tests:** Automatically provisions a runner, restores dependencies using cached Astral `uv`, and executes unit tests via `pytest`.
2.  **Build and Push:** Compiles the Docker image and pushes it to the GitHub Container Registry (`ghcr.io/shdrn2402/my_family_budget/budget_bot:latest`).
3.  **VPS Deploy:** Connects to the DigitalOcean VPS via SSH:
    *   Creates an automatic pre-deployment database dump inside `./backups/` to prevent data loss.
    *   Regenerates the local `.env` configuration file from GitHub Secrets.
    *   Copies `compose.yaml` to the server and pulls the new bot image.
    *   Launches services using `docker compose` in detached mode.

> [!NOTE]
> Commits containing `[skip ci]` in their message skip the pipeline, including the PR checks. Use it only for docs-only changes. When merging such a PR, use **Squash and merge** with `[skip ci]` in the title so the commit on `main` carries the tag.

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
