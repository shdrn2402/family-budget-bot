# Known Issues

This document tracks known bugs, limitations, and ongoing issues in the project.

## 1. Category Editing Overwrites Global Aliases
**Status:** Open / Design Decision Needed
**Date Discovered:** June 26, 2026

**Description:**
When a user manually changes the category of an individual transaction via the Telegram bot interface (in `bot/handlers/inline_menu.py`), the bot automatically executes an `INSERT ... ON CONFLICT DO UPDATE` into the `item_aliases` table. 
This means that changing the category of a single transaction permanently changes the global default category for that merchant for all future (and past, if re-imported) transactions.

**Symptoms:**
- User buys a mop for 50 ILS at a discount store (e.g., "Dan Deal") which is normally categorized as "Junk Food" (for cheap snacks).
- User changes this specific 50 ILS transaction to "Home Maintenance" via the bot.
- All future transactions from "Dan Deal" will now automatically be categorized as "Home Maintenance" instead of "Junk Food".

**Potential Workarounds/Solutions to Investigate:**
1. **User Training / Workaround:** Instruct the user to rename the transaction first (e.g., from "Dan Deal" to "Dan Deal Mop") before changing its category. This creates a new alias without touching the original.
2. **Checkbox / Inline Button Toggle:** When changing a category, ask the user: "Apply to this transaction only?" vs "Apply to all future transactions from this merchant?".
3. **Decouple Logic:** Remove the automatic alias update from the transaction edit flow completely, and rely solely on dedicated "Train Alias" workflows.
