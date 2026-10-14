from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Mapping
from typing import Any, Self

import httpx
from tenacity import (
    AsyncRetrying,
    before_sleep_log,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from goszakup_ai.core.config import Settings

log = logging.getLogger(__name__)

Json = dict[str, Any]

GRAPHQL_PATH = "/v3/graphql"
_RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})


class OwsError(Exception):
    pass


class OwsAuthError(OwsError):
    pass


class OwsHTTPError(OwsError):
    def __init__(self, status: int, url: str) -> None:
        super().__init__(f"OWS HTTP {status} for {url}")
        self.status = status
        self.url = url


class OwsRetryableError(OwsHTTPError):
    pass


class OwsGraphQLError(OwsError):
    def __init__(self, errors: list[Json]) -> None:
        super().__init__(f"OWS GraphQL errors: {errors}")
        self.errors = errors


class _RateLimiter:
    def __init__(self, rate_per_sec: float) -> None:
        self._interval = 1.0 / rate_per_sec
        self._lock = asyncio.Lock()
        self._next_at = 0.0

    async def wait(self) -> None:
        async with self._lock:
            delay = self._next_at - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            self._next_at = time.monotonic() + self._interval


class OwsClient:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._http = httpx.AsyncClient(
            base_url=settings.ows_base_url,
            headers={
                "Authorization": f"Bearer {settings.ows_token.get_secret_value()}",
                "Accept": "application/json",
            },
            timeout=settings.ows_timeout_sec,
            transport=transport,
        )
        self._semaphore = asyncio.Semaphore(settings.ows_max_concurrency)
        self._limiter = _RateLimiter(settings.ows_rate_limit_per_sec)
        self._max_attempts = settings.ows_max_attempts
        self._retry_base_delay = settings.ows_retry_base_delay_sec

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._http.aclose()

    async def get(self, path: str, params: Mapping[str, Any] | None = None) -> Any:
        return await self._request("GET", path, params=params)

    async def rest_pages(
        self, path: str, params: Mapping[str, Any] | None = None
    ) -> AsyncIterator[Json]:
        next_url: str | None = path
        while next_url:
            page: Json = await self.get(next_url, params=params)
            yield page
            next_url = page.get("next_page") or None
            params = None  # next_page already contains the cursor

    async def graphql(self, query: str, variables: Mapping[str, Any] | None = None) -> Json:
        body: Json = await self._request(
            "POST", GRAPHQL_PATH, json={"query": query, "variables": dict(variables or {})}
        )
        if body.get("errors"):
            raise OwsGraphQLError(body["errors"])
        return body

    async def graphql_pages(
        self,
        query: str,
        root_field: str,
        variables: Mapping[str, Any] | None = None,
    ) -> AsyncIterator[list[Json]]:
        # query must declare $after: Int
        after: int | None = None
        while True:
            body = await self.graphql(query, {**(variables or {}), "after": after})
            items: list[Json] = (body.get("data") or {}).get(root_field) or []
            if items:
                yield items
            page_info = (body.get("extensions") or {}).get("pageInfo") or {}
            if not items or not page_info.get("hasNextPage"):
                return
            after = page_info["lastId"]

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Json | None = None,
    ) -> Any:
        self._ensure_own_host(url)
        retrying = AsyncRetrying(
            retry=retry_if_exception_type((httpx.TransportError, OwsRetryableError)),
            wait=wait_exponential_jitter(multiplier=self._retry_base_delay, max=60),
            stop=stop_after_attempt(self._max_attempts),
            before_sleep=before_sleep_log(log, logging.WARNING),
            reraise=True,
        )
        async for attempt in retrying:
            with attempt:
                await self._limiter.wait()
                async with self._semaphore:
                    response = await self._http.request(method, url, params=params, json=json)
                return self._parse(response)
        raise AssertionError("unreachable")

    def _ensure_own_host(self, url: str) -> None:
        target = httpx.URL(url)
        if target.is_absolute_url and target.host != self._http.base_url.host:
            raise OwsError(f"Refusing to send the OWS token to a foreign host: {target.host}")

    @staticmethod
    def _parse(response: httpx.Response) -> Any:
        url = str(response.request.url)
        if response.status_code in (401, 403):
            raise OwsAuthError(
                f"OWS rejected the token (HTTP {response.status_code}) for {url}; check OWS_TOKEN"
            )
        if response.status_code in _RETRYABLE_STATUSES:
            raise OwsRetryableError(response.status_code, url)
        if response.is_error:
            raise OwsHTTPError(response.status_code, url)
        return response.json()
