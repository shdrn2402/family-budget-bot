"""
Pins user registration against a real database: register_user, check_user_exists,
get_user_info (bot/database.py). Replaces a mocked test that could not fail.
"""
import psycopg

from bot.database import check_user_exists, get_user_info, register_user

NEW_USER_ID = 2001


async def test_unknown_user_does_not_exist(db: psycopg.AsyncConnection) -> None:
    assert await check_user_exists(NEW_USER_ID, conn=db) is False


async def test_registered_user_exists_with_its_name_and_role(db: psycopg.AsyncConnection) -> None:
    assert await register_user(NEW_USER_ID, "New User", is_admin=True, conn=db) is True

    assert await check_user_exists(NEW_USER_ID, conn=db) is True
    info = await get_user_info(NEW_USER_ID, conn=db)
    assert info is not None
    assert (info["name"], info["is_admin"]) == ("New User", True)


async def test_registering_again_keeps_the_existing_user(db: psycopg.AsyncConnection) -> None:
    await register_user(NEW_USER_ID, "New User", conn=db)

    assert await register_user(NEW_USER_ID, "Renamed", is_admin=True, conn=db) is True

    info = await get_user_info(NEW_USER_ID, conn=db)
    assert info is not None
    assert (info["name"], info["is_admin"]) == ("New User", False)
