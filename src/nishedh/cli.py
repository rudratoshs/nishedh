"""Command line: `nishedh sweep`, `nishedh report`, `nishedh budget`."""

from __future__ import annotations

import csv
import json
import os
import sys
from pathlib import Path

import typer

from nishedh.registry.eta import EtaRegistry
from nishedh.registry.pesticides import load
from nishedh.search.client import SearchClient
from nishedh.store import Store
from nishedh.sweep import QUERIES, Sweeper

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / ".cache"
app = typer.Typer(add_completion=False, help="Flag Indian marketplace listings for regulatory review.")


def _api_key() -> str | None:
    key = os.environ.get("SERPAPI_API_KEY")
    env = ROOT / ".env"
    if not key and env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("SERPAPI_API_KEY="):
                key = line.split("=", 1)[1].strip()
    return key


@app.command()
def sweep(
    pack: str = typer.Argument(..., help=f"one of: {', '.join(QUERIES)}"),
    live: bool = typer.Option(False, help="spend live SerpApi searches (otherwise cached results only)"),
    max_live: int = typer.Option(40, help="most live searches this sweep may spend"),
    max_details: int = typer.Option(20, help="most Amazon product pages to fetch"),
    max_lens: int = typer.Option(10, help="most Google Lens label checks"),
) -> None:
    """Search one product category, assess every listing, store the findings."""
    client = SearchClient(_api_key() if live else None, CACHE / "serpapi", offline=not live)
    eta = EtaRegistry(CACHE / "eta", offline=not live)
    store = Store(CACHE / "nishedh.sqlite")
    try:
        r = Sweeper(client, store, load(), eta).run(pack, max_live=max_live if live else 0, max_details=max_details, max_lens=max_lens)
    finally:
        client.close()
        store.close()
    typer.echo(f"run {r.run_id}: {r.listings} listings, {r.judged} in scope; searches: {r.live} live, {r.cached} cached")
    for reason, n in sorted(r.by_reason.items(), key=lambda kv: -kv[1]):
        typer.echo(f"  {reason:<22} {n}")
    for s in r.skipped_searches:
        typer.echo(f"  skipped: {s}", err=True)


@app.command()
def report(
    pack: str = typer.Argument(...),
    fmt: str = typer.Option("csv", "--format", help="csv or json"),
    include_clear: bool = typer.Option(False, help="also list listings that passed"),
) -> None:
    """Print the latest run's findings for review (most serious first). Seller and store names are never included."""
    store = Store(CACHE / "nishedh.sqlite")
    run = store.latest_run(pack)
    if run is None:
        raise typer.BadParameter(f"no sweep for {pack!r} yet")
    order = {"banned_item": 0, "not_in_registry": 1, "information_missing": 2, "registry_mismatch": 3, "clear": 4}
    conf = {"high": 0, "medium": 1, "low": 2}
    rows = sorted(store.findings(run), key=lambda f: (order[f["reason"]], conf[f["confidence"]]))
    rows = [f for f in rows if include_clear or f["reason"] != "clear"]
    store.close()
    if fmt == "json":
        public = ("pack", "reason", "confidence", "verdict", "marketplace", "title", "url", "listing_id", "checks", "notes")
        json.dump([{k: f[k] for k in public} for f in rows], sys.stdout, ensure_ascii=False, indent=1)
        return
    w = csv.writer(sys.stdout)
    w.writerow(["reason", "confidence", "marketplace", "title", "url", "why", "evidence"])
    for f in rows:
        top = f["checks"][0]
        evidence = "; ".join(f'{e["field"]}: "{e["text"]}"' for c in f["checks"] for e in c["evidence"])
        w.writerow([f["reason"], f["confidence"], f["marketplace"], f["title"], f["url"], top["explanation"], evidence])


@app.command()
def budget() -> None:
    """Live SerpApi searches used this month, from the local ledger."""
    client = SearchClient(None, CACHE / "serpapi", offline=True)
    typer.echo(f"{client.used_this_month()} of {client.monthly_cap} live searches used this month (plan: 250)")


@app.command()
def serve(port: int = typer.Option(8787), host: str = typer.Option("127.0.0.1")) -> None:
    """Open the local review dashboard."""
    import uvicorn

    from nishedh.web.app import create_app

    uvicorn.run(create_app(CACHE), host=host, port=port, log_level="warning")


def main() -> None:
    app()
