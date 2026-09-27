"""Types shared by every rule pack: reason codes, verdicts, checks and findings.

A finding is never a legal conclusion. It records what the listing said and where, which official
source it was checked against, and one reason code:

    banned_item          the product or a named ingredient may not be sold or listed at all
    not_in_registry      a named ingredient or approval is absent from, or refused by, the registry
    information_missing  the listing does not state what the rules require it to state
    registry_mismatch    registered, but not in the stated strength, form, model or band
    clear                everything stated matches the registry

The verdict is the most serious reason across all checks; checks[0] always explains it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from nishedh.extract.pesticide import Found


class Reason(str, Enum):
    BANNED_ITEM = "banned_item"
    NOT_IN_REGISTRY = "not_in_registry"
    INFORMATION_MISSING = "information_missing"
    REGISTRY_MISMATCH = "registry_mismatch"
    CLEAR = "clear"


class Verdict(str, Enum):
    BANNED = "banned"
    UNREGISTERED_OR_HIDDEN = "unregistered_or_hidden"
    REGISTERED = "registered"


VERDICT_OF = {
    Reason.BANNED_ITEM: Verdict.BANNED,
    Reason.NOT_IN_REGISTRY: Verdict.UNREGISTERED_OR_HIDDEN,
    Reason.INFORMATION_MISSING: Verdict.UNREGISTERED_OR_HIDDEN,
    Reason.REGISTRY_MISMATCH: Verdict.UNREGISTERED_OR_HIDDEN,
    Reason.CLEAR: Verdict.REGISTERED,
}
SEVERITY = [Reason.BANNED_ITEM, Reason.NOT_IN_REGISTRY, Reason.INFORMATION_MISSING, Reason.REGISTRY_MISMATCH, Reason.CLEAR]
CONFIDENCE_ORDER = {"high": 0, "medium": 1, "low": 2}


@dataclass(frozen=True)
class Check:
    """One reason, with what triggered it and the official source it was checked against."""
    reason: Reason
    confidence: str             # "high" | "medium" | "low"
    explanation: str
    evidence: tuple[Found, ...]
    source: str                 # which official list, e.g. "banned_refused_restricted"


@dataclass
class Finding:
    verdict: Verdict
    reason: Reason
    confidence: str
    checks: list[Check]
    notes: list[str] = field(default_factory=list)   # restricted-use conditions, context for the reviewer


def finalize(checks: list[Check], notes: list[str]) -> Finding:
    """A finding from its checks: most serious first, verdict and reason from checks[0]."""
    checks = sorted(checks, key=lambda c: (SEVERITY.index(c.reason), CONFIDENCE_ORDER[c.confidence]))
    worst = checks[0]
    return Finding(VERDICT_OF[worst.reason], worst.reason, worst.confidence, checks, notes)


def with_extra(finding: Finding, checks: list[Check], notes: list[str]) -> Finding:
    """The finding with more checks and notes added, its verdict recomputed."""
    return finalize([*finding.checks, *checks], [*finding.notes, *notes])
