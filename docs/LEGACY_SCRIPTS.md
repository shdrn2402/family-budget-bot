# Removed legacy scripts

One-off and deprecated scripts that were removed from `scripts/` (issue #4).
They are kept in git history. To view one, check out the listed commit, e.g.:

```bash
git show 5c2905b:scripts/import_historical_cash.py
```

| Script | Purpose | Why removed | Last commit containing it |
|---|---|---|---|
| `scripts/import_historical_cash.py` | One-time import of historical cash expenses (2023–2025) from the previous bot's CSV export into the shared cash account, plus a balance-correction row. | Completed one-off migration. Its category mapping uses IDs that no longer match the current category seed, so re-running it would misfile data. | `5c2905b` |
| `scripts/generate_bit_csv.py` | One-time helper: parsed historical Bit CSV exports with the Bit parser and wrote a combined CSV for manual categorization before loading. | Completed one-off migration. | `6421eb4` |
| `scripts/deprecated/create_db.sh` | Early bootstrap script: created the database user, database, `budget` schema and tables on a host Postgres via `sudo -u postgres psql`. | Superseded by the containerized setup; its schema was already outdated. | `2bad886` |
| `scripts/deprecated/extract_aliases_fibisave.py` | One-time extraction of merchant names from Bank Leumi (FibiSave) statements into an aliases YAML file. | Completed; the resulting aliases live in the production database (`app.merchant_rules`), not in the repo. | `d0e8b95` |
| `scripts/deprecated/extract_aliases_isracard.py` | One-time extraction of merchant names from Isracard statements into an aliases YAML file. | Completed; the resulting aliases live in the production database (`app.merchant_rules`), not in the repo. | `d0e8b95` |
| `scripts/__init__.py` | Empty package marker. | Nothing imports from `scripts`. | `28dabf6` |
