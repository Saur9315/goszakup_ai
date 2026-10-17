from __future__ import annotations

import json
import os
from collections.abc import Iterator
from typing import Any

import httpx

API_URL = os.environ.get("API_URL", "http://localhost:8000").rstrip("/")
TIMEOUT = httpx.Timeout(60.0, connect=5.0)
STREAM_TIMEOUT = httpx.Timeout(300.0, connect=5.0)


class ApiError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


def _detail(r: httpx.Response) -> str:
    try:
        detail = r.json().get("detail", r.text)
    except ValueError:
        detail = r.text
    return detail if isinstance(detail, str) else json.dumps(detail, ensure_ascii=False)


class Api:
    def __init__(self, token: str | None = None) -> None:
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            r = httpx.request(
                method, API_URL + path, headers=self.headers, timeout=TIMEOUT, **kwargs
            )
        except httpx.HTTPError as e:
            raise ApiError(0, f"API недоступен ({API_URL}): {e}") from e
        if r.status_code >= 400:
            raise ApiError(r.status_code, _detail(r))
        return r.json()

    def get(self, path: str, **params: Any) -> Any:
        return self._request("GET", path, params={k: v for k, v in params.items() if v})

    def post(self, path: str, body: dict[str, Any]) -> Any:
        return self._request("POST", path, json=body)

    def stream(self, question: str, thread_id: str | None) -> Iterator[tuple[str, dict[str, Any]]]:
        body = {"question": question, "thread_id": thread_id}
        try:
            with httpx.stream(
                "POST",
                API_URL + "/api/ask/stream",
                json=body,
                headers=self.headers,
                timeout=STREAM_TIMEOUT,
            ) as r:
                if r.status_code >= 400:
                    r.read()
                    raise ApiError(r.status_code, _detail(r))
                event = "message"
                for line in r.iter_lines():
                    if line.startswith("event: "):
                        event = line.removeprefix("event: ")
                    elif line.startswith("data: "):
                        yield event, json.loads(line.removeprefix("data: "))
        except httpx.HTTPError as e:
            raise ApiError(0, f"API недоступен ({API_URL}): {e}") from e
