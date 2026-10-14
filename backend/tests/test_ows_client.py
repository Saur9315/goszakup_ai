import json

import httpx
import pytest
import respx

from goszakup_ai.core.config import Settings
from goszakup_ai.ows import OwsAuthError, OwsClient, OwsError

BASE = "https://ows.test"
TOKEN = "secret-test-token"


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://test@localhost/test",
        ows_token=TOKEN,
        ows_base_url=BASE,
        ows_rate_limit_per_sec=1000,
        ows_max_attempts=3,
        ows_retry_base_delay_sec=0.01,
    )


@respx.mock
async def test_rest_pages_follow_next_page(settings: Settings) -> None:
    route = respx.get(f"{BASE}/v3/lots").mock(
        side_effect=[
            httpx.Response(200, json={"items": [1], "next_page": "/v3/lots?search_after=1"}),
            httpx.Response(200, json={"items": [2], "next_page": ""}),
        ]
    )
    async with OwsClient(settings) as client:
        pages = [page async for page in client.rest_pages("/v3/lots")]

    assert [p["items"] for p in pages] == [[1], [2]]
    assert route.calls[1].request.url.params["search_after"] == "1"
    assert route.calls[0].request.headers["Authorization"] == f"Bearer {TOKEN}"


@respx.mock
async def test_transient_errors_are_retried(settings: Settings) -> None:
    route = respx.get(f"{BASE}/v3/trd-buy").mock(
        side_effect=[httpx.Response(503), httpx.Response(200, json={"total": 0})]
    )
    async with OwsClient(settings) as client:
        assert await client.get("/v3/trd-buy") == {"total": 0}
    assert route.call_count == 2


@respx.mock
async def test_auth_error_is_not_retried_and_hides_token(settings: Settings) -> None:
    route = respx.get(f"{BASE}/v3/plans").mock(return_value=httpx.Response(401))
    async with OwsClient(settings) as client:
        with pytest.raises(OwsAuthError) as exc_info:
            await client.get("/v3/plans")
    assert route.call_count == 1
    assert TOKEN not in str(exc_info.value)


@respx.mock
async def test_token_is_never_sent_to_foreign_host(settings: Settings) -> None:
    respx.get(f"{BASE}/v3/lots").mock(
        return_value=httpx.Response(200, json={"next_page": "https://evil.test/v3/lots"})
    )
    foreign = respx.get("https://evil.test/v3/lots")
    async with OwsClient(settings) as client:
        with pytest.raises(OwsError, match="foreign host"):
            async for _ in client.rest_pages("/v3/lots"):
                pass
    assert not foreign.called


@respx.mock
async def test_graphql_pages_use_last_id_cursor(settings: Settings) -> None:
    route = respx.post(f"{BASE}/v3/graphql").mock(
        side_effect=[
            httpx.Response(
                200,
                json={
                    "data": {"Lots": [{"id": 1}, {"id": 10}]},
                    "extensions": {"pageInfo": {"hasNextPage": True, "lastId": 10}},
                },
            ),
            httpx.Response(
                200,
                json={
                    "data": {"Lots": [{"id": 11}]},
                    "extensions": {"pageInfo": {"hasNextPage": False, "lastId": 11}},
                },
            ),
        ]
    )
    query = "query($after: Int) { Lots(limit: 2, after: $after) { id } }"
    async with OwsClient(settings) as client:
        pages = [page async for page in client.graphql_pages(query, "Lots")]

    assert [[item["id"] for item in page] for page in pages] == [[1, 10], [11]]
    second_body = json.loads(route.calls[1].request.content)
    assert second_body["variables"]["after"] == 10
