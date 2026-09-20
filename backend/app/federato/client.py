"""Transport layer for the Federato hack-north data handler.

Two responsibilities: keep a live bearer token, and turn a query payload into
results. Everything above this module works in terms of dicts.
"""
from __future__ import annotations

import base64
import json
import time
from typing import Any

import httpx

from ..config import (
    AUDIENCE,
    AUTH_URL,
    CLIENT_ID,
    CLIENT_SECRET,
    HANDLER_URL,
    TOKEN_CACHE,
)


class FederatoError(RuntimeError):
    """An error the data layer reported back to us.

    The handler catches everything and rethrows `new Error(e.message)`, so the
    error class and code only survive inside the message text, shaped like
    `[VALIDATION_ERROR] Unknown operator "$grt" {"operator":"$grt"}`. We parse
    that prefix back out so callers can branch on it.
    """

    def __init__(self, message: str, payload: dict | None = None):
        super().__init__(message)
        self.raw = message
        self.payload = payload
        self.code = None
        if message.startswith("["):
            end = message.find("]")
            if end > 0:
                self.code = message[1:end]

    @property
    def is_validation_error(self) -> bool:
        return self.code == "VALIDATION_ERROR"


def _decode_jwt_exp(token: str) -> float:
    """Read `exp` out of a JWT without verifying it, so we can pre-empt 401s."""
    try:
        part = token.split(".")[1]
        pad = "=" * (-len(part) % 4)
        claims = json.loads(base64.urlsafe_b64decode(part + pad))
        return float(claims.get("exp", 0))
    except Exception:
        return 0.0


class FederatoClient:
    """Synchronous client with an on-disk token cache.

    Tokens last 4 hours. We cache to disk so restarting the server during a
    hackathon demo doesn't mint a new one every time, and refresh 5 minutes
    before expiry rather than waiting for a 401.
    """

    def __init__(self, client_id: str = CLIENT_ID, client_secret: str = CLIENT_SECRET):
        self._id = client_id
        self._secret = client_secret
        self._token: str | None = None
        self._expires_at: float = 0.0
        self._http = httpx.Client(timeout=60.0)
        self.call_count = 0
        self._load_cached_token()

    # ---- auth ----------------------------------------------------------

    def _load_cached_token(self) -> None:
        if not TOKEN_CACHE.exists():
            return
        try:
            cached = json.loads(TOKEN_CACHE.read_text())
            if cached.get("client_id") == self._id:
                self._token = cached["access_token"]
                self._expires_at = cached["expires_at"]
        except Exception:
            pass

    def _store_token(self) -> None:
        try:
            TOKEN_CACHE.write_text(
                json.dumps(
                    {
                        "client_id": self._id,
                        "access_token": self._token,
                        "expires_at": self._expires_at,
                    }
                )
            )
        except OSError:
            pass  # a read-only FS shouldn't break the run

    def token(self) -> str:
        if self._token and time.time() < self._expires_at - 300:
            return self._token
        if not self._id or not self._secret:
            raise FederatoError(
                "Missing FEDERATO_CLIENT_ID / FEDERATO_CLIENT_SECRET. "
                "Copy .env.example to .env and fill them in."
            )
        resp = self._http.post(
            AUTH_URL,
            json={
                "client_id": self._id,
                "client_secret": self._secret,
                "audience": AUDIENCE,
                "grant_type": "client_credentials",
            },
        )
        if resp.status_code != 200:
            raise FederatoError(f"Token mint failed ({resp.status_code}): {resp.text[:300]}")
        body = resp.json()
        self._token = body["access_token"]
        exp = _decode_jwt_exp(self._token)
        self._expires_at = exp or time.time() + body.get("expires_in", 14400)
        self._store_token()
        return self._token

    # ---- transport -----------------------------------------------------

    def _call(self, action: str, payload: Any = None, _retry: bool = True) -> Any:
        body: dict[str, Any] = {"action": action}
        if payload is not None:
            body["payload"] = payload
        resp = self._http.post(
            HANDLER_URL,
            json=body,
            headers={
                "Authorization": f"Bearer {self.token()}",
                "Content-Type": "application/json",
            },
        )
        self.call_count += 1

        if resp.status_code == 401 and _retry:
            # Token rejected mid-session; drop it and mint once more.
            self._token, self._expires_at = None, 0.0
            return self._call(action, payload, _retry=False)

        if resp.status_code >= 400:
            raise FederatoError(f"HTTP {resp.status_code}: {resp.text[:500]}", payload)

        data = resp.json()
        # outputOnly=true is documented to strip the envelope but the handler
        # still wraps in {"output": [{"data": ...}]}, so unwrap defensively.
        if isinstance(data, dict) and "output" in data:
            out = data["output"]
            if isinstance(out, list) and out and isinstance(out[0], dict):
                data = out[0].get("data", out[0])
        if isinstance(data, dict) and "error" in data and "results" not in data:
            raise FederatoError(str(data["error"]), payload)
        if isinstance(data, str):
            raise FederatoError(data, payload)
        return data

    def schema(self) -> dict:
        return self._call("schema")

    def query(self, payload: dict) -> dict:
        """Run one query. Returns {total, results|groups, resource}."""
        return self._call("query", payload)

    def close(self) -> None:
        self._http.close()
