from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 1


@dataclass(frozen=True)
class TokenClaims:
    user_id: int
    username: str
    expires_at: int


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, digest = stored.split("$")
        actual = hashlib.scrypt(
            password.encode(), salt=_unb64(salt), n=int(n), r=int(r), p=int(p), dklen=32
        )
    except ValueError:
        return False
    return hmac.compare_digest(actual, _unb64(digest))


DUMMY_HASH = hash_password(secrets.token_hex(16))


def _sign(secret: str, payload: str) -> str:
    return _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())


def new_claims(user_id: int, username: str, ttl_seconds: int) -> TokenClaims:
    return TokenClaims(user_id, username, int(time.time()) + ttl_seconds)


def encode_token(secret: str, claims: TokenClaims) -> str:
    payload = _b64(
        json.dumps(
            {"uid": claims.user_id, "sub": claims.username, "exp": claims.expires_at}
        ).encode()
    )
    return f"{payload}.{_sign(secret, payload)}"


def decode_token(secret: str, token: str) -> TokenClaims | None:
    payload, _, signature = token.partition(".")
    try:
        if not signature or not hmac.compare_digest(signature, _sign(secret, payload)):
            return None
        data = json.loads(_unb64(payload))
        claims = TokenClaims(int(data["uid"]), str(data["sub"]), int(data["exp"]))
    except (TypeError, ValueError, KeyError):
        return None
    return claims if claims.expires_at >= time.time() else None
