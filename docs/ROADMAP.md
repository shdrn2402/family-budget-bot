# Roadmap: from Telegram bot to data platform

The project is moving from a Telegram bot with a database to a small, production-style data platform. The bot stays as the household's entry point. Statement ingestion, reconciliation and categorization move into a tested ELT pipeline, and the outputs are an on-demand dashboard and a monthly report per card billing cycle.

**Target architecture (hybrid):**
- The bot and PostgreSQL stay on the existing VPS.
- Statement files land in an S3 bucket (immutable, versioned). S3 events go through SQS to Lambda parsers, which write Parquet (bronze).
- A loader appends bronze into raw tables in Postgres. dbt builds the staging, intermediate and mart layers.
- Orchestration starts with scheduled GitHub Actions and moves to Dagster on the VPS.
- Infrastructure is managed with Terraform.

Each stage ends in a deployable state with the bot still working.

## Done: the bot (before the data platform)
- [x] Manual entry in the `item account amount` format, resolved through an alias database.
- [x] Statement import (Isracard, Leumi, Bit) with deduplication, bulk categorization and batch upload summaries.
- [x] Transit (Bit) and cash wallet tracking, with reconciliation between Bit and card/bank statements.
- [x] Inline editing, interactive `/history`, `/uncategorized`, localization.
- [x] Docker deployment with CI/CD to the VPS.

## Stage 0: Stabilize and strip [DONE]
*Goal: a safe base before any new architecture.*
- [x] Production fixes: timezone, access checks on callbacks and admin commands.
- [x] Alembic migrations from a baseline of the production schema, applied at startup; restore is an explicit manual script.
- [x] CI runs the tests on every pull request, including integration tests against a disposable PostgreSQL.
- [x] Reconciliation fixes: deduplication before matching, matching on the same account, working Bit reconciliation.
- [x] The AI layer (Gemini, voice input, NL→SQL analytics, charts) and dead code removed. Text that can't be parsed gets a reply showing the expected format.

## Stage 1: Core refactor, ready for ingestion
*Goal: separate domain logic from Telegram so parsers can run anywhere.*
- [ ] Split into packages: `budget_core/` (domain types, parsers, rules), `bot/` (Telegram adapter), `db/` (repositories on a connection pool).
- [ ] Parsers become pure functions returning typed records, with a parser version and statement-level metadata (statement period, card charge date).
- [ ] Household-specific values move out of the code into database tables or private config. Seed data is split into a public category tree, private household data and a fake household for tests.
- [ ] Committed, hand-made statement fixtures for each format, with golden outputs, plus a scenario dataset of named reconciliation cases.
- [ ] Secret scanning (gitleaks) in pre-commit and CI.

## Stage 2: Raw landing zone in S3
*Goal: every statement file is preserved immutably.*
- [ ] Terraform: an encrypted, versioned S3 bucket with public access blocked, a least-privilege IAM identity for the bot, and a budget alarm.
- [ ] The bot uploads every file to the landing zone, keyed by its hash, and records it in an ingest registry. It keeps importing in-process as before (dual-write).
- [ ] Local development with MinIO; tests with moto.

## Stage 3: Serverless parsing to bronze
*Goal: event-driven ingestion.*
- [ ] S3 notifications → SQS (with a dead-letter queue) → Lambda, deployed from GitHub Actions with OIDC.
- [ ] The Lambda reuses the `budget_core` parsers, validates the schema and writes Parquet to bronze.
- [ ] Bronze output is compared with the in-process import for every file.

## Stage 4: Warehouse and dbt
*Goal: business logic moves into tested SQL models.*
- [ ] An idempotent loader appends bronze into `raw` tables.
- [ ] dbt models: staging, then deduplication, reconciliation, internal transfers and categorization, then marts (transactions, period summaries, wallet balances, data completeness, anomalies).
- [ ] Category overrides with an explicit scope (one transaction or a whole merchant), which resolves the global alias overwrite in `docs/KNOWN_ISSUES.md`.
- [ ] `dbt build` runs in CI on the scenario fixtures; the dbt docs site is published.
- [ ] The bot reads from the marts, and the in-process import path is removed.

## Stage 5: Orchestration and observability
- [ ] Scheduled runs, then Dagster: bronze → raw → dbt, with backfill and replay from the landing zone.
- [ ] Freshness, data quality and dead-letter alerts to a Telegram admin chat.
- [ ] A completeness check per billing period, with reminders about missing statements.

## Stage 6: Deliverables
*All serving is private to the household.*
- [ ] On-demand dashboard over the marts, run locally through an SSH tunnel with a read-only role.
- [ ] Monthly PDF report per card billing cycle, triggered when the period's data is complete and delivered through Telegram.
- [ ] Bot `/stats` command with quick text totals.

## Stage 7 (optional): AI as a pipeline component
- [ ] A written summary section in the monthly report, generated from aggregates only and checked against the data.
- [ ] LLM categorization for merchants the rules can't place, with cached results and tracked confidence.
- [ ] Natural-language questions over the marts only, through a read-only role.
