"""Verify Equipment Type Approval (ETA) numbers against the Department of Telecommunications' public certificates.

Every self-declared ETA certificate is public at the URL encoded in its QR code:
    https://saralsanchar.gov.in/wpc_new/eta_cert_QR_pdf.php?<base64 of the ETA number>
The page is HTML (despite the name) and lists the model, make, equipment category, frequency
range(s) and the gazette notification that exempts the device. For an unknown number the same
template comes back with every field empty.

Only these public certificate links are used. The registry's search page is captcha-protected and
is not touched. Pages are cached on disk and fetched at most one every `delay` seconds.
"""

from __future__ import annotations

import base64
import html as htmllib
import re
import time
from dataclasses import dataclass
from pathlib import Path

import httpx

CERT_URL = "https://saralsanchar.gov.in/wpc_new/eta_cert_QR_pdf.php?{token}"
USER_AGENT = "Nishedh/0.1 (marketplace compliance research; https://github.com/rudratoshs/nishedh)"
_NUMBER = re.compile(r"^ETA-SD-\d{11}$")
# "446.006-446.19 MHz", "2400 MHz-2483.5 MHz", "446.00625 MHz to 446.19375 MHz", "2.4 GHz": a unit
# may follow either number, and a single value is a band of one frequency.
_FREQ = r"(\d+(?:\.\d+)?)\s*(?:([GMk])Hz)?"
_BAND = re.compile(rf"{_FREQ}\s*(?:-|–|to)\s*{_FREQ}", re.IGNORECASE)
_SINGLE = re.compile(r"(\d+(?:\.\d+)?)\s*([GMk])Hz", re.IGNORECASE)
# Every genuine certificate page, found or not, carries these; anything else (an error or
# maintenance page) is not evidence either way.
_TEMPLATE_MARKERS = ("WPC Wing", "Registration No:")


class EtaUnavailable(RuntimeError):
    """The certificate page could not be fetched or is not a certificate page; nothing is concluded."""


@dataclass(frozen=True)
class EtaCertificate:
    number: str
    found: bool
    date: str = ""
    model: str = ""
    make: str = ""
    category: str = ""
    bands_mhz: tuple[tuple[float, float], ...] = ()
    notifications: tuple[str, ...] = ()
    url: str = ""


def cert_url(number: str) -> str:
    token = base64.b64encode(number.encode()).decode()
    return CERT_URL.format(token=token)


def _cells(page: str) -> list[str]:
    """The page's visible text, split at tags into non-empty cells."""
    page = re.sub(r"<(script|style)\b.*?</\1>", "", page, flags=re.DOTALL | re.IGNORECASE)
    parts = re.split(r"<[^>]+>", page)
    return [c for c in (re.sub(r"\s+", " ", htmllib.unescape(p)).strip() for p in parts) if c]


def _after(cells: list[str], label: str) -> str:
    """The first cell after the one that starts with `label`, unless it is the next numbered field."""
    for i, c in enumerate(cells):
        if c.startswith(label) and i + 1 < len(cells):
            nxt = cells[i + 1]
            return "" if re.fullmatch(r"\d+\.", nxt) else nxt
    return ""


def _section(cells: list[str], start_label: str, end_label: str) -> list[str]:
    try:
        i = next(k for k, c in enumerate(cells) if c.startswith(start_label))
    except StopIteration:
        return []
    j = next((k for k in range(i + 1, len(cells)) if cells[k].startswith(end_label)), len(cells))
    return cells[i + 1 : j]


def _to_mhz(value: float, unit: str) -> float:
    return {"g": value * 1000, "m": value, "k": value / 1000}[unit.lower()]


def is_certificate_page(page: str) -> bool:
    return all(marker in page for marker in _TEMPLATE_MARKERS)


def parse_certificate(number: str, page: str) -> EtaCertificate:
    if not is_certificate_page(page):
        raise EtaUnavailable(f"{number}: the response is not an ETA certificate page")
    cells = _cells(page)
    reg = next((c for c in cells if c.startswith("Registration No:")), "")
    date_match = re.search(r"Date:\s*(\d{2}-\d{2}-\d{4})", reg)
    model = _after(cells, "Model")
    if not date_match and not model:
        return EtaCertificate(number=number, found=False, url=cert_url(number))
    bands = []
    for c in _section(cells, "Frequency range(s)", "Max output power"):
        covered = []
        for m in _BAND.finditer(c):
            unit = m.group(2) or m.group(4)
            if not unit:
                continue
            lo, hi = sorted((_to_mhz(float(m.group(1)), m.group(2) or unit), _to_mhz(float(m.group(3)), m.group(4) or unit)))
            bands.append((lo, hi))
            covered.append(m.span())
        for m in _SINGLE.finditer(c):
            if not any(a <= m.start() < b for a, b in covered):
                f = _to_mhz(float(m.group(1)), m.group(2))
                bands.append((f, f))
    notifications = tuple(c for c in _section(cells, "Applicable Gazette", "RF Test Report") if "(E)" in c)
    return EtaCertificate(
        number=number, found=True, date=date_match.group(1) if date_match else "", model=model,
        make=_after(cells, "Make"), category=_after(cells, "Equipment category"),
        bands_mhz=tuple(bands), notifications=notifications, url=cert_url(number),
    )


class EtaRegistry:
    """Fetches and caches certificate pages; one request at most every `delay` seconds."""

    def __init__(self, cache_dir: Path, http: httpx.Client | None = None, delay: float = 2.0, offline: bool = False) -> None:
        self.cache_dir = cache_dir
        self.offline = offline
        self._owns_http = http is None
        self._http = http or httpx.Client(timeout=60, headers={"User-Agent": USER_AGENT})
        self._delay = delay
        self._last = 0.0
        cache_dir.mkdir(parents=True, exist_ok=True)

    def close(self) -> None:
        """Close the HTTP client, unless it was passed in (then its owner closes it)."""
        if self._owns_http:
            self._http.close()

    def lookup(self, number: str) -> EtaCertificate | None:
        """The certificate for this ETA number; None when offline and not cached."""
        if not _NUMBER.fullmatch(number):
            raise ValueError(f"not an ETA-SD number: {number!r}")
        path = self.cache_dir / f"{number}.html"
        if not path.exists():
            if self.offline:
                return None
            wait = self._delay - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            try:
                resp = self._http.get(cert_url(number))
                resp.raise_for_status()
            except httpx.HTTPError as e:
                raise EtaUnavailable(f"{number}: certificate page unavailable ({type(e).__name__})") from None
            finally:
                self._last = time.monotonic()
            if not is_certificate_page(resp.text):
                raise EtaUnavailable(f"{number}: the response is not an ETA certificate page")   # never cached
            path.write_text(resp.text)
        return parse_certificate(number, path.read_text())
