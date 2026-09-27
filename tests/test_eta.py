"""ETA certificates: parsing real saved pages, caching, and the radio rules that use them.

Fixtures are the public certificate pages for ETA-SD-20201208695 (Motorola T82, PMR446) and for a
number that does not exist (the same template with every field empty), saved on 27 Sep 2026.
"""

from pathlib import Path

import httpx
import pytest

from nishedh.extract.radio import extract_radio
from nishedh.registry.eta import EtaRegistry, cert_url, parse_certificate
from nishedh.verdict.base import Reason
from nishedh.verdict.radio import assess_radio

FIX = Path(__file__).parent / "fixtures" / "eta"
GOOD, MISSING = "ETA-SD-20201208695", "ETA-SD-20990100001"


def page(number):
    return (FIX / f"{number}.html").read_text()


def test_cert_url_is_the_qr_code_url():
    assert cert_url(GOOD).endswith("?RVRBLVNELTIwMjAxMjA4Njk1")


def test_parse_real_certificate():
    c = parse_certificate(GOOD, page(GOOD))
    assert c.found and c.model == "T82" and c.make.startswith("MOTOROLA")
    assert c.category == "Transreceiver in 446MHz band" and c.date == "19-01-2021"
    assert c.bands_mhz == ((446.006, 446.19),)
    assert c.notifications == ("1047 (E) Dated 18-10-2018",)   # the PMR446 exemption notification


def test_parse_unknown_number():
    c = parse_certificate(MISSING, page(MISSING))
    assert not c.found and c.model == "" and c.bands_mhz == ()


def test_registry_caches_and_never_refetches(tmp_path):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, text=page(GOOD))

    reg = EtaRegistry(tmp_path, http=httpx.Client(transport=httpx.MockTransport(handler)), delay=0)
    assert reg.lookup(GOOD).found and reg.lookup(GOOD).found
    assert len(calls) == 1 and calls[0].url.host == "saralsanchar.gov.in"


def test_registry_offline_and_validation(tmp_path):
    reg = EtaRegistry(tmp_path, offline=True)
    assert reg.lookup(GOOD) is None
    with pytest.raises(ValueError):
        reg.lookup("../../etc/passwd")


def judge(title, certs):
    return assess_radio(extract_radio({"title": title}), certs, title)


def test_matching_certificate_is_clear_high():
    c = parse_certificate(GOOD, page(GOOD))
    f = judge(f"Motorola T82 PMR446 walkie talkie 446.0-446.2 MHz {GOOD}", {GOOD: c})
    assert (f.reason, f.confidence) == (Reason.CLEAR, "high")


def test_borrowed_certificate_is_a_mismatch():
    c = parse_certificate(GOOD, page(GOOD))
    f = judge(f"Baofeng BF-888S PMR446 446.0-446.2 MHz {GOOD}", {GOOD: c})
    assert f.reason is Reason.REGISTRY_MISMATCH and "does not name" in f.checks[-1].explanation


def test_nonexistent_eta_is_not_in_registry_high():
    c = parse_certificate(MISSING, page(MISSING))
    f = judge(f"Walkie talkie 446.0-446.2 MHz {MISSING}", {MISSING: c})
    assert (f.reason, f.confidence) == (Reason.NOT_IN_REGISTRY, "high")


def test_unchecked_eta_is_low_confidence():
    f = judge(f"Walkie talkie 446.0-446.2 MHz {GOOD}", {})
    assert f.confidence == "low" and "not been checked" in f.checks[-1].explanation


def test_unreadable_certificate_band_is_never_clear():
    from nishedh.registry.eta import parse_certificate as parse
    c = parse(GOOD, page(GOOD).replace("446.006-446.19 MHz", "see annexure"))
    f = judge(f"Motorola T82 PMR446 walkie talkie 446.0-446.2 MHz {GOOD}", {GOOD: c})
    assert f.reason is not Reason.CLEAR and "could not be read" in f.checks[0].explanation


def test_certificate_band_formats():
    for text, want in (("2400 MHz-2483.5 MHz", ((2400.0, 2483.5),)),
                       ("446.00625 MHz to 446.19375 MHz", ((446.00625, 446.19375),)),
                       ("2.4 GHz", ((2400.0, 2400.0),))):
        assert parse_certificate(GOOD, page(GOOD).replace("446.006-446.19 MHz", text)).bands_mhz == want


def test_error_page_is_not_cached_or_judged(tmp_path):
    from nishedh.registry.eta import EtaUnavailable

    def handler(request):
        return httpx.Response(200, text="<html>Service Unavailable</html>")

    reg = EtaRegistry(tmp_path, http=httpx.Client(transport=httpx.MockTransport(handler)), delay=0)
    with pytest.raises(EtaUnavailable):
        reg.lookup(GOOD)
    assert not list(tmp_path.glob("*.html"))


def test_http_error_is_unavailable_not_a_verdict(tmp_path):
    from nishedh.registry.eta import EtaUnavailable
    reg = EtaRegistry(tmp_path, http=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503))), delay=0)
    with pytest.raises(EtaUnavailable):
        reg.lookup(GOOD)


def test_model_match_ignores_hyphens_and_spacing():
    c = parse_certificate(GOOD, page(GOOD))
    for title in ("MotorolaT82 PMR446 446.0-446.2 MHz", "Motorola T-82 PMR446 446.0-446.2 MHz"):
        f = judge(f"{title} {GOOD}", {GOOD: c})
        assert f.reason is Reason.CLEAR, title


# ---- A certificate must cover the frequency the listing states (external review, 27 Sep 2026) ----

def test_certificate_for_another_band_is_a_mismatch():
    c = parse_certificate(GOOD, page(GOOD))            # certifies 446.006-446.19 MHz (PMR446 channels)
    f = judge(f"Motorola T82 walkie talkie 2400 MHz {GOOD}", {GOOD: c})
    assert f.reason is Reason.REGISTRY_MISMATCH and "does not cover the stated frequency" in f.checks[-1].explanation


def test_band_edges_match_certified_channel_centres():
    c = parse_certificate(GOOD, page(GOOD))
    f = judge(f"Motorola T82 PMR446 446.0-446.2 MHz {GOOD}", {GOOD: c})
    assert f.reason is Reason.CLEAR
