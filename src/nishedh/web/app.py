"""Local review dashboard: findings, the "why was this flagged?" chain, exports and complaint drafts.

Run with `nishedh serve`. It reads the evidence store and cached SerpApi responses; it never
searches. Merchant names stay in the store and are not shown or exported.
"""

from __future__ import annotations

import csv
import io
import json
from collections import Counter
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.templating import Jinja2Templates

from nishedh.registry.pesticides import load
from nishedh.sources import source_map
from nishedh.store import Store

REASON_ORDER = ["banned_item", "not_in_registry", "information_missing", "registry_mismatch", "clear"]
REASON_LABEL = {
    "banned_item": "Banned item", "not_in_registry": "Not in registry", "information_missing": "Information missing",
    "registry_mismatch": "Registry mismatch", "clear": "Clear",
}
CONF_ORDER = {"high": 0, "medium": 1, "low": 2}
PUBLIC_FIELDS = ("pack", "reason", "confidence", "marketplace", "title", "url", "listing_id")


def create_app(cache_dir: Path) -> FastAPI:
    app = FastAPI(title="Nishedh", docs_url=None, redoc_url=None)
    templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
    templates.env.globals.update(REASON_LABEL=REASON_LABEL)
    sources = source_map(load())

    def store() -> Store:
        return Store(cache_dir / "nishedh.sqlite")

    def findings(pack: str | None) -> tuple[int | None, list[dict[str, Any]]]:
        s = store()
        try:
            run = s.latest_run(pack)
            rows = s.findings(run) if run else []
            runs = {r["id"]: dict(r) for r in s.db.execute("SELECT * FROM runs").fetchall()}
        finally:
            s.close()
        for r in rows:
            r["run"] = runs.get(r["run_id"], {})
        rows.sort(key=lambda f: (REASON_ORDER.index(f["reason"]), CONF_ORDER[f["confidence"]], f["title"]))
        return run, rows

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request, pack: str = "pesticides", reason: str = "", confidence: str = "", show_clear: bool = False) -> Any:
        run, rows = findings(pack)
        counts = Counter(r["reason"] for r in rows)
        shown = [
            r for r in rows
            if (show_clear or r["reason"] != "clear")
            and (not reason or r["reason"] == reason) and (not confidence or r["confidence"] == confidence)
        ]
        run_info = rows[0]["run"] if rows else {}
        return templates.TemplateResponse(request, "index.html", {
            "pack": pack, "run": run, "run_info": run_info, "rows": shown, "counts": counts, "total": len(rows),
            "reason": reason, "confidence": confidence, "show_clear": show_clear, "reason_order": REASON_ORDER,
            "marketplaces": Counter(r["marketplace"] for r in rows if r["reason"] != "clear").most_common(),
        })

    def one(pack: str, listing_id: str) -> dict[str, Any]:
        _, rows = findings(pack)
        for r in rows:
            if r["listing_id"] == listing_id:
                return r
        raise HTTPException(404, "finding not found in the latest run")

    @app.get("/finding/{pack}/{listing_id:path}", response_class=HTMLResponse)
    def finding(request: Request, pack: str, listing_id: str) -> Any:
        f = one(pack, listing_id)
        return templates.TemplateResponse(request, "finding.html", {"f": f, "pack": pack, "sources": sources})

    @app.get("/complaint/{pack}/{listing_id:path}", response_class=PlainTextResponse)
    def complaint(pack: str, listing_id: str) -> str:
        return complaint_text(one(pack, listing_id), sources)

    @app.get("/raw/{engine}/{search_id}")
    def raw(engine: str, search_id: str) -> Any:
        if not engine.isidentifier() or not all(c in "0123456789abcdef" for c in search_id):
            raise HTTPException(400, "bad id")
        path = cache_dir / "serpapi" / engine / f"{search_id}.json"
        if not path.exists():
            raise HTTPException(404, "not cached")
        return JSONResponse(json.loads(path.read_text()))

    @app.get("/export/{pack}.{fmt}")
    def export(pack: str, fmt: str) -> Response:
        _, rows = findings(pack)
        public = [{k: r[k] for k in PUBLIC_FIELDS} | {"why": r["checks"][0]["explanation"]} for r in rows]
        if fmt == "json":
            return JSONResponse(public)
        if fmt != "csv":
            raise HTTPException(404, "use .csv or .json")
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=[*PUBLIC_FIELDS, "why"])
        w.writeheader()
        w.writerows(public)
        return Response(buf.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="nishedh-{pack}.csv"'})

    return app


def complaint_text(f: dict[str, Any], sources: dict[str, Any]) -> str:
    """A draft request for review, for a person to verify and file (National Consumer Helpline / CCPA)."""
    lines = [
        "DRAFT – verify the listing and its label before filing. This is an automated screening result,",
        "not a legal determination.",
        "",
        "To: Central Consumer Protection Authority / National Consumer Helpline (1915, consumerhelpline.gov.in)",
        f"Subject: Request to review a listing on {f['marketplace']} – {REASON_LABEL[f['reason']].lower()}",
        "",
        f"Listing: {f['title']}",
        f"Link: {f['url']}",
        f"Marketplace: {f['marketplace']}",
        f"Observed: {f['run'].get('started_at', '')[:10]} via SerpApi ({f['engine']} search)",
        "",
        "Concerns:",
    ]
    cited: dict[str, Any] = {}
    for i, c in enumerate(f["checks"], 1):
        if c["reason"] == "clear":
            continue
        lines.append(f"  {i}. {c['explanation']}")
        for e in c["evidence"]:
            lines.append(f'     Listing text ({e["field"]}): "{e["text"]}"')
        if c["source"] in sources:
            cited[c["source"]] = sources[c["source"]]
    for n in f["notes"]:
        lines.append(f"  Note: {n}")
    lines += ["", "Official sources checked:"]
    for s in cited.values():
        lines.append(f"  - {s.title}{f' (as on {s.as_on})' if s.as_on else ''}: {s.url}")
    lines += ["", "Requested action: review the listing and, if confirmed, direct its removal under the applicable rules."]
    return "\n".join(lines) + "\n"
