import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from goszakup_ai.api.app import User, authorize_thread, remember_thread
from goszakup_ai.api.auth import (
    decode_token,
    encode_token,
    hash_password,
    new_claims,
    verify_password,
)
from goszakup_ai.db.models import AppUser

SECRET = "test-secret"


def test_password_hash_roundtrip() -> None:
    stored = hash_password("correct horse")

    assert verify_password("correct horse", stored)
    assert not verify_password("wrong horse", stored)
    assert not verify_password("anything", "not-a-hash")


def test_token_roundtrip_and_rejections() -> None:
    token = encode_token(SECRET, new_claims(7, "analyst", 60))
    payload, _, signature = token.partition(".")

    claims = decode_token(SECRET, token)
    assert claims is not None and (claims.user_id, claims.username) == (7, "analyst")
    assert decode_token("other-secret", token) is None
    assert decode_token(SECRET, payload + "." + signature[::-1]) is None
    assert decode_token(SECRET, encode_token(SECRET, new_claims(7, "analyst", -1))) is None
    assert decode_token(SECRET, "мусор") is None


async def test_threads_are_private_to_their_owner(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    async with sessions.begin() as db:
        db.add_all(
            [
                AppUser(id=1, username="a", password_hash="x"),
                AppUser(id=2, username="b", password_hash="x"),
            ]
        )
    alice, bob = User(id=1, username="a"), User(id=2, username="b")
    thread = uuid.uuid4()

    await authorize_thread(sessions, thread, None)
    await remember_thread(sessions, str(thread), alice, "Сколько договоров?")
    await authorize_thread(sessions, thread, alice)
    for stranger in (bob, None):
        with pytest.raises(HTTPException) as e:
            await authorize_thread(sessions, thread, stranger)
        assert e.value.status_code == 404
