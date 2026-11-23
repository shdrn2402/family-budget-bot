"""
Pins user registration against a real database: db.users register, exists and get.
Replaces a mocked test that could not fail.
"""
import psycopg

from db import users

NEW_USER_ID = 2001


async def test_unknown_user_does_not_exist(db: psycopg.AsyncConnection) -> None:
    assert await users.exists(db, NEW_USER_ID) is False


async def test_registered_user_exists_with_its_name_and_role(db: psycopg.AsyncConnection) -> None:
    await users.register(db, NEW_USER_ID, "New User", is_admin=True)

    assert await users.exists(db, NEW_USER_ID) is True
    info = await users.get(db, NEW_USER_ID)
    assert info is not None
    assert (info["name"], info["is_admin"]) == ("New User", True)


async def test_registering_again_keeps_the_existing_user(db: psycopg.AsyncConnection) -> None:
    await users.register(db, NEW_USER_ID, "New User")

    await users.register(db, NEW_USER_ID, "Renamed", is_admin=True)

    info = await users.get(db, NEW_USER_ID)
    assert info is not None
    assert (info["name"], info["is_admin"]) == ("New User", False)
