"""Build the public demo snapshot in `demo/` from the local SerpApi cache.

The demo lets anyone replay the 27 Sep 2026 live run without an API key (`nishedh demo`). Each
response is reduced to the fields Nishedh reads (`nishedh.sanitise`).

Run: uv run python scripts/build_demo.py   (then check `uv run pytest tests/test_demo.py`)
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from nishedh.sanitise import sanitise

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / ".cache"
OUT = ROOT / "demo"


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    n = 0
    for path in sorted((SRC / "serpapi").glob("*/*.json")):
        engine = path.parent.name
        stored = json.loads(path.read_text())
        target = OUT / "serpapi" / engine / path.name
        target.parent.mkdir(parents=True, exist_ok=True)
        clean = {"params": stored["params"], "fetched_at": stored["fetched_at"], "data": sanitise(engine, stored["data"])}
        target.write_text(json.dumps(clean, ensure_ascii=False, indent=1) + "\n")
        n += 1
    if (SRC / "eta").exists():
        shutil.copytree(SRC / "eta", OUT / "eta")
    print(f"wrote {n} sanitised SerpApi responses to {OUT.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
