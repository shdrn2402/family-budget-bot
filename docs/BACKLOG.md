# 📝 Backlog & Ideas (For the Future)

In this file, we record ideas, technical improvements, and feature requests that pop up during development but do not block current roadmap phases.

## Postponed Tasks & Enhancements:
- [ ] **AI-Powered Universal Ingestion:** Move away from bank-specific parsers. Leverage LLMs to infer column layouts and dynamically parse arbitrary bank formats (CSV/XLSX).
- [ ] **Multi-Family / Shared Budget Support:** Introduce `family_id` scoping to database entities. Support shared views alongside personal expense tracking with member filters (`[All]`, `[Mine]`, `[Name]`) in history.
- [ ] **Fuzzy Search for Aliases:** Implement fast local fuzzy string matching (e.g., via `rapidfuzz` or `difflib`) to catch slight typos in merchant names before hitting the LLM API, reducing latency and token costs.
- [ ] **Structured File Logging:** Introduce log rotation (e.g., via `RotatingFileHandler`) to capture error context across container lifecycle restarts instead of relying solely on stdout.
- [ ] **Proactive Financial Advisor:** Background cron agent that runs scheduled analyses on monthly spending, detects budget anomalies, and surfaces actionable advice via push notifications.
- [ ] **Self-Service Card & Account Management:** Bot-driven UI for updating card masks (e.g., migrating from `4787` to `9999`) while preserving historical ledger links, keeping card masks decoupled from logical account entities.
- [ ] **Admin Control Panel:** Dedicated Telegram interface for users with `is_admin = true` to onboard family members, manage accounts, and assign permissions directly from chat.