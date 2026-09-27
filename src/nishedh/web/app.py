"""Local review dashboard: findings, the "why was this flagged?" chain, exports and complaint drafts.

Run with `nishedh serve`. It reads the evidence store and cached SerpApi responses; it never
searches. Merchant names stay in the store and are not shown or exported.
"""

from __future__ import annotations

import csv
import io
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from nishedh.listing import marketplace_of
from nishedh.registry.pesticides import load
from nishedh.sources import source_map
from nishedh.store import Store

REASON_ORDER = ["banned_item", "not_in_registry", "information_missing", "registry_mismatch", "clear"]
REASON_LABEL = {
    "banned_item": "Banned item", "not_in_registry": "Not in registry", "information_missing": "Information missing",
    "registry_mismatch": "Registry mismatch", "clear": "Clear",
}
# What each result means, for someone who has never read the rules.
REASON_HELP = {
    "banned_item": "The product itself is not allowed to be sold online in India.",
    "not_in_registry": "The chemical or product is not on the government's approved list.",
    "information_missing": "The listing leaves out something the law says it must show.",
    "registry_mismatch": "The listing's details do not match the official record.",
    "clear": "Nothing wrong was found.",
}
CONF_LABEL = {"high": "Strong evidence", "medium": "Good lead", "low": "Weak signal"}
CONF_HELP = {
    "high": "The listing's own words break a written rule.",
    "medium": "Clear signs, but a person should confirm (for example, a matching photo).",
    "low": "Only the search-result title was read, not the full product page.",
}
CONF_ORDER = {"high": 0, "medium": 1, "low": 2}
PER_PAGE = 24
PACKS = ("pesticides", "radio")
SORTS = {"serious": "Most serious first", "price_low": "Price: low to high", "price_high": "Price: high to low",
         "title": "Name (A–Z)"}
PUBLIC_FIELDS = ("pack", "reason", "confidence", "marketplace", "title", "url", "listing_id")


def create_app(cache_dir: Path, demo_note: str = "") -> FastAPI:
    app = FastAPI(title="Nishedh", docs_url=None, redoc_url=None)
    templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
    app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
    templates.env.globals.update(REASON_LABEL=REASON_LABEL, REASON_HELP=REASON_HELP, CONF_LABEL=CONF_LABEL,
                                 CONF_HELP=CONF_HELP, REASON_ORDER=REASON_ORDER, headline=headline,
                                 DEMO_NOTE=demo_note)
    templates.env.filters["web_url"] = web_url
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
    def index(request: Request, pack: str = "pesticides", reason: str = "review", confidence: str = "",
              market: str = "", q: str = "", sort: str = "serious", page: str = "1") -> Any:
        # Unknown values fall back to the defaults instead of an error page or a silently empty list.
        pack = pack if pack in PACKS else "pesticides"
        reason = reason if reason in (*REASON_ORDER, "review", "all") else "review"
        confidence = confidence if confidence in CONF_ORDER else ""
        sort = sort if sort in SORTS else "serious"
        page_no = int(page) if page.isdigit() else 1
        run, rows = findings(pack)
        counts = Counter(r["reason"] for r in rows)
        needle = q.strip().lower()
        shown = [
            r for r in rows
            if (reason == "all" or (reason == "review" and r["reason"] != "clear") or r["reason"] == reason)
            and (not confidence or r["confidence"] == confidence)
            and (not market or r["marketplace"] == market)
            and (not needle or needle in r["title"].lower())
        ]
        if sort == "title":
            shown.sort(key=lambda f: f["title"].lower())
        elif sort in ("price_low", "price_high"):
            priced = [f for f in shown if _price(f["price"]) is not None]
            priced.sort(key=lambda f: _price(f["price"]) or 0.0, reverse=sort == "price_high")
            shown = priced + [f for f in shown if _price(f["price"]) is None]
        pages = max(1, math.ceil(len(shown) / PER_PAGE))
        page_no = min(max(page_no, 1), pages)
        params = {"pack": pack, "reason": reason, "confidence": confidence, "market": market, "q": q, "sort": sort}
        return templates.TemplateResponse(request, "index.html", {
            "pack": pack, "run": run, "run_info": rows[0]["run"] if rows else {}, "total": len(rows),
            "rows": shown[(page_no - 1) * PER_PAGE : page_no * PER_PAGE], "matched": len(shown), "counts": counts,
            "page": page_no, "pages": pages, "params": params, "sorts": SORTS, "overview": overview(),
            "markets": sorted({r["marketplace"] for r in rows}),
            "strong": sum(1 for r in rows if r["reason"] != "clear" and r["confidence"] != "low"),
            "story": next((r for r in rows if r["lens_search_id"] and r["reason"] == "not_in_registry"), None)
            if pack == "pesticides" else next((r for r in rows if r["reason"] == "banned_item"), None),
        })

    def overview() -> dict[str, int]:
        """Totals across every pack, for the page header."""
        out = {"checked": 0, "strong": 0}
        for pack in PACKS:
            _, rows = findings(pack)
            out["checked"] += len(rows)
            out["strong"] += sum(1 for r in rows if r["reason"] != "clear" and r["confidence"] != "low")
        return out

    @app.get("/how-it-works", response_class=HTMLResponse)
    def how(request: Request) -> Any:
        return templates.TemplateResponse(request, "how.html", {"page_name": "how", "sources": sources})

    @app.get("/faq", response_class=HTMLResponse)
    def faq(request: Request) -> Any:
        return templates.TemplateResponse(request, "faq.html", {"page_name": "faq"})

    def one(pack: str, listing_id: str) -> dict[str, Any]:
        _, rows = findings(pack)
        for r in rows:
            if r["listing_id"] == listing_id:
                return r
        raise HTTPException(404, "finding not found in the latest run")

    @app.get("/finding/{pack}/{listing_id:path}", response_class=HTMLResponse)
    def finding(request: Request, pack: str, listing_id: str) -> Any:
        if pack not in PACKS:
            raise HTTPException(404, "unknown category")
        f = one(pack, listing_id)
        return templates.TemplateResponse(request, "finding.html", {
            "f": f, "pack": pack, "sources": sources, "photos": lens_photos(cache_dir, f),
        })

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
        if pack not in PACKS:
            raise HTTPException(404, "unknown category")
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


def headline(f: dict[str, Any]) -> str:
    """One plain sentence saying what is wrong, for the list and the top of a finding."""
    reason, first = f["reason"], f["checks"][0]["explanation"]
    everything = " ".join(c["explanation"] for c in f["checks"])
    if reason == "clear":
        return "Nothing wrong found."
    if f["pack"] == "radio":
        if reason == "banned_item":
            if first.startswith("Listed as a jammer"):
                return "Signal jammers are not allowed to be sold online in India."
            if first.startswith("Listed as a mobile signal booster"):
                return "Mobile signal boosters are not allowed to be sold online in India."
            return "Is sold as working on a frequency band that needs a government licence."
        if reason == "information_missing":
            missing = [w for w, k in (("its frequency", "frequency"), ("its government approval (ETA) number", "(ETA)"))
                       if any(k in c["explanation"] and c["reason"] == "information_missing" for c in f["checks"])]
            return "Does not say " + " or ".join(missing) + "." if missing else "Missing information the rules require."
        if reason == "not_in_registry":
            return "Its approval number is not on the government's register."
        if first.startswith("States "):
            return "States an unusual frequency band that needs checking."
        if "could not be read" in first:
            return "Its approval certificate could not be read automatically; check it by hand."
        return "Its approval certificate does not match this product."
    if reason == "banned_item":
        return "Contains a chemical that is banned in India."
    if reason == "not_in_registry":
        m = re.search(r"\. (\w+) is named in the CCPA", everything)
        if m:
            return f"The same photo is sold elsewhere as {m.group(1)}, a weed killer the government ordered off sale."
        m = re.match(r"(.+?) is in the Schedule", first)
        if m:
            return f"{m.group(1)} is not registered for use in India."
        return "Names a chemical that is not on India's approved list."
    if reason == "information_missing":
        m = re.match(r'"(.+?)" names no chemical on any official list', first)
        if m:
            return f'Names "{m.group(1)}", which is on no official list. It may be a brand name. Needs checking.'
        if ("active" in first.lower() and "names no chemical" in first) or "never names it" in first:
            return "Claims an \"active\" formula but never says which chemical is inside."
        if f["confidence"] == "low":
            return "The title does not say which chemical is inside."
        return "The listing never says which chemical is inside."
    return "The chemical's strength does not match any registered product."


def web_url(url: str) -> str:
    """Only http(s) links from search data reach an href or src; anything else becomes "#"."""
    return url if isinstance(url, str) and url.lower().startswith(("https://", "http://")) else "#"


def _price(text: str) -> float | None:
    m = re.search(r"\d[\d,]*(?:\.\d+)?", text or "")
    return float(m.group(0).replace(",", "")) if m else None


def lens_photos(cache_dir: Path, f: dict[str, Any]) -> list[dict[str, str]]:
    """Photos of the Lens matches a finding cites, so a reviewer can compare them with the listing's."""
    if not f.get("lens_search_id"):
        return []
    path = cache_dir / "serpapi" / "google_lens" / f"{f['lens_search_id']}.json"
    if not path.exists():
        return []
    cited = {e["text"] for c in f["checks"] for e in c["evidence"] if e["field"].startswith("same photo")}
    out = []
    raw = json.loads(path.read_text())
    data = raw.get("data", raw)   # cache files wrap the response as {"params", "fetched_at", "data"}
    for v in data.get("visual_matches") or []:
        if v.get("title") in cited and v.get("thumbnail"):
            out.append({"title": str(v["title"]), "thumbnail": str(v["thumbnail"]),
                        "site": marketplace_of(str(v.get("link", "")), str(v.get("source", "")))})
    return out[:3]


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
        f"Observed: {(f['run'].get('data_as_of') or f['run'].get('started_at', ''))[:10]} via SerpApi ({f['engine']} search)",
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
