import os
import yaml
import logging
from datetime import datetime
from bot.config import Config
from db import household, pool

logger = logging.getLogger(__name__)

async def create_database_dump() -> str | None:
    """
    Creates a PostgreSQL database dump using pg_dump.
    Returns the file path to the dump or None if it failed.
    """
    try:
        import asyncio
        import shutil

        if not shutil.which("pg_dump"):
            logger.error("pg_dump utility not found on the system.")
            return None

        backup_dir = "/app/backups"
        os.makedirs(backup_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = os.path.join(backup_dir, f"db_backup_{timestamp}.sql")
        
        env = os.environ.copy()
        if Config.DB_PASSWORD:
            env["PGPASSWORD"] = Config.DB_PASSWORD
            
        cmd = [
            "pg_dump",
            "-h", Config.DB_HOST,
            "-p", str(Config.DB_PORT),
            "-U", Config.DB_USER,
            "-d", Config.DB_NAME,
            "-F", "p", # Plain text SQL
            "-f", filepath
        ]
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            logger.error(f"pg_dump failed: {stderr.decode('utf-8', errors='replace')}")
            return None
            
        return filepath
    except Exception as e:
        logger.error(f"Error creating database dump: {e}")
        return None

async def export_household_to_yaml() -> str | None:
    """
    Exports the household (users, accounts, aliases, merchant rules and names) in the
    household-file format, so it can be loaded back with scripts/load_household.py.
    Returns the file path, or None if it failed. The file is private household data.
    """
    try:
        async with pool.connection() as conn:
            data = await household.export(conn)

        backup_dir = "/app/backups"
        os.makedirs(backup_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = os.path.join(backup_dir, f"household_backup_{timestamp}.yaml")

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write("# PRIVATE household backup. Load with scripts/load_household.py (dry run first).\n")
            yaml.safe_dump(data, f, allow_unicode=True, default_flow_style=None, sort_keys=False, width=120)

        return filepath
    except Exception as e:
        logger.error(f"Error exporting the household to yaml: {e}")
        return None
