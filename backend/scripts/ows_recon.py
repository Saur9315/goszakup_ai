from __future__ import annotations

import argparse
import asyncio
import csv
import json
import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from goszakup_ai.core.config import REPO_ROOT, get_settings
from goszakup_ai.core.scope import TARGET_BINS
from goszakup_ai.ows import OwsClient, OwsError, OwsHTTPError

log = logging.getLogger("ows_recon")

OUT_DIR = REPO_ROOT / "data" / "recon"

COUNT_ENDPOINTS: dict[str, str] = {
    "plans": "/v3/plans/{bin}",
    "trd_buy_as_organizer": "/v3/trd-buy/bin/{bin}",
    "lots_as_customer": "/v3/lots/bin/{bin}",
    "contracts_as_customer": "/v3/contract/customer/{bin}",
    "contracts_as_supplier": "/v3/contract/supplier/{bin}",
}

REFS = (
    "ref_units",
    "ref_kato",
    "ref_buy_status",
    "ref_lots_status",
    "ref_contract_status",
    "ref_trade_methods",
    "ref_subject_type",
    "ref_pln_point_status",
    "ref_currency",
    "ref_enstru",
)

INTROSPECTION_QUERY = """
query Introspection {
  __schema {
    queryType { name }
    types {
      kind name description
      fields(includeDeprecated: true) {
        name description
        args { name type { ...TypeRef } }
        type { ...TypeRef }
      }
      inputFields { name description type { ...TypeRef } }
      enumValues(includeDeprecated: true) { name }
    }
  }
}
fragment TypeRef on __Type {
  kind name
  ofType { kind name ofType { kind name ofType { kind name ofType { kind name } } } }
}
"""


def _dump(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("saved %s", path.relative_to(REPO_ROOT))


def _type_str(t: dict[str, Any]) -> str:
    if t["kind"] == "NON_NULL":
        return _type_str(t["ofType"]) + "!"
    if t["kind"] == "LIST":
        return f"[{_type_str(t['ofType'])}]"
    return str(t["name"])


def _render_schema_md(schema: dict[str, Any]) -> str:
    types = {t["name"]: t for t in schema["types"] if not t["name"].startswith("__")}
    query_type = types[schema["queryType"]["name"]]
    lines = ["# OWS v3 GraphQL schema (introspection summary)", "", "## Query root fields", ""]
    for f in query_type["fields"]:
        args = ", ".join(f"{a['name']}: {_type_str(a['type'])}" for a in f["args"])
        lines.append(f"- `{f['name']}({args})` -> `{_type_str(f['type'])}`")
    for name in sorted(types):
        t = types[name]
        if t["kind"] not in ("OBJECT", "INPUT_OBJECT", "ENUM") or t is query_type:
            continue
        lines += ["", f"## {t['kind'].lower()} `{name}`"]
        if t.get("description"):
            lines.append(f"_{t['description'].strip()}_")
        for f in t.get("fields") or t.get("inputFields") or []:
            desc = f" — {f['description'].strip()}" if f.get("description") else ""
            lines.append(f"- `{f['name']}`: `{_type_str(f['type'])}`{desc}")
        for v in t.get("enumValues") or []:
            lines.append(f"- `{v['name']}`")
    return "\n".join(lines) + "\n"


async def cmd_schema(client: OwsClient) -> None:
    body = await client.graphql(INTROSPECTION_QUERY)
    schema = body["data"]["__schema"]
    _dump(OUT_DIR / "graphql_schema.json", schema)
    md_path = OUT_DIR / "graphql_schema.md"
    md_path.write_text(_render_schema_md(schema), encoding="utf-8")
    log.info("saved %s", md_path.relative_to(REPO_ROOT))


async def _total(client: OwsClient, path: str) -> int | str:
    try:
        page = await client.get(path)
    except OwsHTTPError as e:
        return f"ERR {e.status}"
    return page.get("total", "?") if isinstance(page, dict) else "?"


async def _count_bin(client: OwsClient, bin_: str) -> dict[str, Any]:
    row: dict[str, Any] = {"bin": bin_}
    try:
        subject = await client.get(f"/v3/subject/biin/{bin_}")
        row["name_ru"] = subject.get("name_ru") or subject.get("nameRu") or ""
    except OwsHTTPError as e:
        row["name_ru"] = f"ERR {e.status}"
    totals = await asyncio.gather(
        *(_total(client, p.format(bin=bin_)) for p in COUNT_ENDPOINTS.values())
    )
    row.update(zip(COUNT_ENDPOINTS, totals, strict=True))
    log.info("%s %s", bin_, row["name_ru"][:60])
    return row


async def cmd_counts(client: OwsClient) -> None:
    rows = await asyncio.gather(*(_count_bin(client, b) for b in TARGET_BINS))
    yesterday = date.today() - timedelta(days=1)
    journal_total = await _total(
        client, f"/v3/journal?date_from={yesterday.isoformat()}&date_to={date.today().isoformat()}"
    )

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    fields = ["bin", "name_ru", *COUNT_ENDPOINTS]
    with (OUT_DIR / "counts.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n{'BIN':<13} " + " ".join(f"{k[:22]:>22}" for k in COUNT_ENDPOINTS) + "  name")
    sums = dict.fromkeys(COUNT_ENDPOINTS, 0)
    for r in rows:
        print(f"{r['bin']:<13} " + " ".join(f"{r[k]!s:>22}" for k in COUNT_ENDPOINTS), end="")
        print(f"  {r['name_ru'][:50]}")
        for k in COUNT_ENDPOINTS:
            if isinstance(r[k], int):
                sums[k] += r[k]
    print(f"{'TOTAL':<13} " + " ".join(f"{sums[k]!s:>22}" for k in COUNT_ENDPOINTS))
    print(f"\njournal changes {yesterday}..today: total={journal_total}")
    log.info("saved data/recon/counts.csv")


async def _save_first_page(client: OwsClient, name: str, path: str) -> Any:
    try:
        page = await client.get(path)
    except OwsHTTPError as e:
        log.warning("%s: HTTP %s at %s", name, e.status, path)
        return None
    _dump(OUT_DIR / "samples" / f"{name}.json", page)
    return page


async def cmd_samples(client: OwsClient, bin_: str) -> None:
    await _save_first_page(client, "subject", f"/v3/subject/biin/{bin_}")
    for name, tpl in COUNT_ENDPOINTS.items():
        page = await _save_first_page(client, name, tpl.format(bin=bin_))
        items = (page or {}).get("items") or []
        if name == "contracts_as_customer" and items:
            await _save_first_page(client, "contract_units", f"/v3/contract/{items[0]['id']}/units")
        if name == "trd_buy_as_organizer" and items:
            await _save_first_page(client, "trd_buy_detail", f"/v3/trd-buy/{items[0]['id']}")
    for ref in REFS:
        await _save_first_page(client, f"refs/{ref}", f"/v3/refs/{ref}")
    today = date.today()
    await _save_first_page(
        client,
        "journal",
        f"/v3/journal?date_from={(today - timedelta(days=1)).isoformat()}"
        f"&date_to={today.isoformat()}",
    )


async def main() -> None:
    parser = argparse.ArgumentParser(description="OWS v3 reconnaissance")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("schema")
    sub.add_parser("counts")
    samples = sub.add_parser("samples")
    samples.add_argument("--bin", default=TARGET_BINS[0])
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    async with OwsClient(get_settings()) as client:
        try:
            if args.cmd == "schema":
                await cmd_schema(client)
            elif args.cmd == "counts":
                await cmd_counts(client)
            else:
                await cmd_samples(client, args.bin)
        except OwsError as e:
            raise SystemExit(f"OWS error: {e}") from e


if __name__ == "__main__":
    asyncio.run(main())
