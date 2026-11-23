import logging
from typing import List, Dict, Any, Optional
import psycopg
from db import accounts, categories, merchant_rules, transactions
import zoneinfo
from datetime import datetime, date, timedelta
from bot.config import Config

def get_local_date() -> date:
    """Returns the current date in the configured local timezone."""
    tz = zoneinfo.ZoneInfo(Config.BOT_TIMEZONE)
    return datetime.now(tz).date()


INCOME_KEYWORDS = ['доход', 'зарплата', 'подработка', 'премия', 'плюс', 'income', 'salary']

def resolve_amount_sign(amount: float, parent_id: int | None) -> float:
    """
    Determine the sign of the amount based on the category's parent.
    parent_id 1 = Income (Always positive)
    parent_id 2 = Transfer (Preserve original sign)
    all others  = Expense (Always negative)
    """
    if parent_id == 1:
        return abs(amount)
    elif parent_id == 2:
        return amount
    else:
        return -abs(amount)

logger = logging.getLogger(__name__)

async def parse_expense_message(text: str, user_id: int, conn: psycopg.AsyncConnection) -> List[Dict[str, Any]]:
    """
    Parses a string like 'кола нал 5, такси сбер 150.5'
    Returns a list of dictionaries with parsed data.
    """
    results: List[Dict[str, Any]] = []
    parts: List[str] = text.split(',')
    
    for part in parts:
        part = part.strip()
        if not part:
            continue
            
        words: List[str] = part.split()
        
        tx_date = None
        words_lower = [w.lower() for w in words]
        
        if 'вчера' in words_lower or 'yesterday' in words_lower:
            tx_date = (get_local_date() - timedelta(days=1)).isoformat()
            target_word = 'вчера' if 'вчера' in words_lower else 'yesterday'
            words.pop(words_lower.index(target_word))
        elif 'позавчера' in words_lower:
            tx_date = (get_local_date() - timedelta(days=2)).isoformat()
            words.pop(words_lower.index('позавчера'))
        elif 'сегодня' in words_lower or 'today' in words_lower:
            tx_date = get_local_date().isoformat()
            target_word = 'сегодня' if 'сегодня' in words_lower else 'today'
            words.pop(words_lower.index(target_word))

        if len(words) < 2:
            results.append({'original': part, 'error': 'not_enough_words'})
            continue
            
        # Find amount from the end to allow optional trailing comments
        amount_idx = -1
        amount = 0.0
        for i in range(len(words)-1, 0, -1): # Need at least 1 word before amount (item_name)
            try:
                amount_str = words[i].replace(',', '.')
                amount = float(amount_str)
                amount_idx = i
                break
            except ValueError:
                continue

        if amount_idx < 1:
            results.append({'original': part, 'error': 'invalid_amount'})
            continue

        if amount_idx >= 2:
            account_alias: str = words[amount_idx - 1].lower()
            item_name: str = " ".join(words[:amount_idx - 1]).lower()
        else:
            account_alias: str = ""
            item_name: str = words[0].lower()

        comment: Optional[str] = " ".join(words[amount_idx + 1:]) if amount_idx < len(words) - 1 else None
        if comment:
            ignored_currencies = {
                'шекелей', 'шекеля', 'шекель', 'шек', 'shekels', 'shekel', 'nis', 'ils', '₪',
                'рублей', 'рубля', 'рубль', 'руб', 'rubles', 'ruble', 'rub',
                'долларов', 'доллара', 'доллар', 'dollars', 'dollar', 'usd', '$',
                'евро', 'euros', 'euro', 'eur', '€'
            }
            comment_words = comment.split()
            filtered_comment_words = []
            for w in comment_words:
                clean_w = w.lower().strip('.,!?;:')
                if clean_w not in ignored_currencies:
                    filtered_comment_words.append(w)
            comment = " ".join(filtered_comment_words) if filtered_comment_words else None
        
        # 4. Resolve Account ID
        account_id: Optional[int] = await resolve_account(account_alias, user_id, conn) if account_alias else None
        
        # An account word was given but it isn't a known alias.
        if account_alias and not account_id:
            results.append({'original': part, 'error': 'unknown_account', 'account_alias': account_alias})
            continue
        
        # 5. Resolve Category ID
        category_id: Optional[int] = await resolve_category_from_alias(item_name, conn)
        
        results.append({
            'original': part,
            'item_name': item_name,
            'amount': amount,
            'account_id': account_id,
            'account_alias': account_alias,
            'category_id': category_id,
            'comment': comment,
            'date': tx_date
        })
        
    return results

async def resolve_account(alias: str, user_id: int, conn: psycopg.AsyncConnection) -> Optional[int]:
    """Find the account a typed word names: 'карта'/'card' is the user's own card, else account_aliases."""
    alias = alias.lower().strip()
    if alias in ['карта', 'card']:
        card = await accounts.find_owned_card(conn, user_id)
        return card['id'] if card else None
    return await accounts.find_by_alias(conn, alias)

async def resolve_category_from_alias(item_name: str, conn: psycopg.AsyncConnection) -> Optional[int]:
    """Find the category of a typed item name (app.merchant_rules)."""
    return await merchant_rules.find_category(conn, item_name.lower().strip())

async def process_expense_text(text: str, user_id: int, conn: psycopg.AsyncConnection) -> List[Dict[str, Any]]:
    """
    Parse a manual entry message. All or nothing: if any part can't be read, only the
    parts with errors are returned, so nothing is saved and the user can resend the message.
    """
    results = await parse_expense_message(text, user_id, conn)
    errors = [item for item in results if 'error' in item]
    return errors or results

async def save_expense_item(item: dict, user_id: int, lang: str, conn: psycopg.AsyncConnection, source_type: str) -> dict:
    """
    Saves a single parsed expense item to the database.
    Checks account type limits, identifies income vs expense, and inserts into DB.
    Returns {"id": int, "db_amount": float, "status": str} on success,
    or {"error": str} on failure.
    """
    amount = item.get('amount', 0.0)
    account_id = item.get('account_id')
    category_id = item.get('category_id')
    item_name = item.get('item_name', '')
    comment = item.get('comment')
    
    if not account_id:
        return {"error": "account_not_found"}
        
    account_type = await accounts.get_type(conn, account_id)
    status = 'confirmed' if account_type == 'cash' else 'pending'
    
    if account_type == 'card':
        if abs(amount) > 150:
            return {"error": "card_limit_exceeded"}
        
    parent_id = await categories.get_parent_id(conn, category_id) if category_id else None

    # If it matched no category but has income keywords, fallback to Other Income (13)
    if not category_id and any(word in item_name.split() for word in INCOME_KEYWORDS):
        category_id = 13
        parent_id = 1

    db_amount = resolve_amount_sign(amount, parent_id)
    
    tx_date = item.get('date') or get_local_date().isoformat()
    
    tx_id = await transactions.insert_manual(
        conn,
        user_id=user_id,
        account_id=account_id,
        category_id=category_id,
        amount=db_amount,
        description=item_name,
        comment=comment,
        day=tx_date,
        source_type=source_type,
        status=status,
    )

    return {
        "id": tx_id,
        "db_amount": db_amount,
        "status": status
    }
