"""Candidate-bound issuer-official content fallback.

This module deliberately keeps issuer pages out of candidate discovery.  An
OpenDART/KRX candidate must already exist; an issuer page can only provide
content for that candidate after the persisted A1/A2 failure and all linkage
checks have passed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from html import unescape
from html.parser import HTMLParser
import hashlib
from pathlib import Path
import re
from typing import Any, Mapping
from urllib.parse import unquote, urlsplit


TIER_A1_OPENDART = "TIER_A1_OPENDART"
TIER_A2_KRX_KIND = "TIER_A2_KRX_KIND"
TIER_B_ISSUER_OFFICIAL = "TIER_B_ISSUER_OFFICIAL"
CANDIDATE_BOUND_FALLBACK_MODE = "CANDIDATE_BOUND_OFFICIAL_CONTENT_FALLBACK"


@dataclass(frozen=True)
class IssuerTrustRule:
    ticker: str
    issuer_aliases: tuple[str, ...]
    scheme: str
    host: str
    path_prefix: str


ISSUER_OFFICIAL_TRUST_REGISTRY: dict[str, IssuerTrustRule] = {
    "005930": IssuerTrustRule(
        ticker="005930",
        issuer_aliases=(
            "삼성전자",
            "Samsung Electronics",
            "Samsung Electronics Co., Ltd.",
        ),
        scheme="https",
        host="www.samsung.com",
        path_prefix="/global/ir/reports-disclosures/",
    ),
}


class _VisibleTextParser(HTMLParser):
    """Extract visible text while ignoring script/style noise."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "noscript", "template"}:
            self._ignored += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript", "template"}:
            self._ignored = max(0, self._ignored - 1)

    def handle_data(self, data: str) -> None:
        if not self._ignored:
            self.parts.append(data)


def _visible_text(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace")
    parser = _VisibleTextParser()
    try:
        parser.feed(text)
        parser.close()
        text = " ".join(parser.parts)
    except Exception:
        # A malformed page is still parsed as text, but never treated as a
        # transport success by the validator below.
        text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", unescape(text)).strip()


def _normalize_issuer(value: str) -> str:
    value = unescape(str(value or "")).lower()
    value = value.replace("(주)", "").replace("co., ltd.", " ")
    value = re.sub(r"\b(?:co\.?\s*,?\s*ltd\.?|company|corporation|limited)\b", " ", value)
    return re.sub(r"[^0-9a-z가-힣]", "", value)


def _normalise_date(raw: str) -> str:
    value = re.sub(r"\s+", " ", str(raw or "")).strip().replace(".", "")
    month_names = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    }
    m = re.fullmatch(r"([A-Za-z]{3,9})\s+(\d{1,2}),?\s+(\d{4})", value)
    if m:
        month = month_names.get(m.group(1).lower()[:3])
        if month:
            try:
                return date(int(m.group(3)), month, int(m.group(2))).isoformat()
            except ValueError:
                return ""
    m = re.fullmatch(r"(\d{4})[-/]?(\d{2})[-/]?(\d{2})", value)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        except ValueError:
            return ""
    return ""


def _normalise_month_day(raw: str, year: int | None = None) -> str:
    """Normalise an issuer-page month/day value, inheriting year when omitted."""
    value = re.sub(r"\s+", " ", str(raw or "")).strip().replace(".", "")
    m = re.fullmatch(r"([A-Za-z]{3,9})\s+(\d{1,2}),?\s*(\d{4})?", value)
    if not m:
        return ""
    chosen_year = int(m.group(3)) if m.group(3) else year
    if chosen_year is None:
        return ""
    month_names = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    }
    month = month_names.get(m.group(1).lower()[:3])
    if not month:
        return ""
    try:
        return date(chosen_year, month, int(m.group(2))).isoformat()
    except ValueError:
        return ""


def _date_pattern() -> str:
    months = r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    return rf"{months}\s+\d{{1,2}}\.?[,]?\s+\d{{4}}"


def parse_issuer_official_document(raw_bytes: bytes) -> dict[str, Any]:
    """Independently derive Samsung's disclosure facts from frozen HTML.

    Caller-provided event/date claims are not consulted.  Repeated conflicting
    issuer, publication, or schedule values are reported as ambiguity.
    """
    text = _visible_text(raw_bytes)
    lower = text.lower()
    blocked_patterns = (
        r"access\s+denied",
        r"captcha",
        r"page\s+not\s+found",
        r"\b(status|error)\s*[:=]\s*(4\d\d|5\d\d)",
        r"temporarily\s+unavailable",
    )
    blocked = any(re.search(pattern, text, re.IGNORECASE) for pattern in blocked_patterns)

    title_matches = re.findall(r"Decision\s+on\s+Stock\s+Split\s*\(\s*Update\s*\)", text, re.IGNORECASE)
    issuer_matches = re.findall(r"Samsung\s+Electronics(?:\s+Co\.,\s*Ltd\.)?", text, re.IGNORECASE)
    ticker_matches = sorted(set(re.findall(r"\bKS(\d{6})\b", text, re.IGNORECASE)))

    title_match = re.search(
        r"Decision\s+on\s+Stock\s+Split\s*\(\s*Update\s*\)\s+(?P<date>" + _date_pattern() + r")",
        text,
        re.IGNORECASE,
    )
    publication_dates = []
    if title_match:
        publication_dates.append(_normalise_date(title_match.group("date")))

    schedule_pattern = re.compile(
        r"Scheduled\s+Listing\s+Date\s+of\s+New\s+Share\s+Certificates\s+"
        r"(?P<active>" + _date_pattern() + r")\s*"
        r"\(\s*originally\s+(?P<previous>"
        r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
        r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|"
        r"Dec(?:ember)?)\s+\d{1,2}\.?[,]?(?:\s+\d{4})?)\s*\)\s*",
        re.IGNORECASE,
    )
    schedule_matches = [
        (
            _normalise_date(m.group("active")),
            _normalise_month_day(m.group("previous"), int(_normalise_date(m.group("active"))[:4]))
            if _normalise_date(m.group("active"))
            else "",
        )
        for m in schedule_pattern.finditer(text)
    ]
    schedule_values = sorted(set(schedule_matches))
    active_date = schedule_values[0][0] if len(schedule_values) == 1 else ""
    previous_date = schedule_values[0][1] if len(schedule_values) == 1 else ""
    event_family = "STOCK_SPLIT" if re.search(r"stock\s+split", lower) else ""
    update_semantics = bool(
        title_matches
        and re.search(r"updated\s+details|originally\s+announced", text, re.IGNORECASE)
    )

    return {
        "parsed_issuer": issuer_matches[0] if len(set(_normalize_issuer(v) for v in issuer_matches)) == 1 and issuer_matches else "",
        "issuer_candidates": sorted(set(issuer_matches)),
        "parsed_ticker": ticker_matches[0] if ticker_matches else "",
        "ticker_candidates": ticker_matches,
        "report_title": title_matches[0] if len(title_matches) == 1 else "",
        "publication_date": publication_dates[0] if len(set(publication_dates)) == 1 and publication_dates else "",
        "event_family": event_family,
        "update_semantics": "UPDATE" if update_semantics else "",
        "official_anchor_type": "NEW_SHARE_LISTING_DATE" if active_date else "",
        "official_anchor_date": active_date,
        "superseded_anchor_date": previous_date,
        "chronology_valid": bool(active_date and previous_date and active_date != previous_date and active_date < previous_date),
        "blocked_page_detected": blocked,
        "body_usable": bool(raw_bytes and len(raw_bytes) > 0 and text and not blocked),
        "text_length": len(text),
    }


def _candidate_date(candidate: Mapping[str, Any]) -> str:
    raw = candidate.get("disclosure_date") or candidate.get("rcept_dt") or ""
    raw = str(raw).strip()
    if re.fullmatch(r"\d{8}", raw):
        return _normalise_date(raw)
    return raw[:10] if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw[:10]) else ""


def _candidate_event(candidate: Mapping[str, Any]) -> str:
    return str(
        candidate.get("event_family")
        or candidate.get("target_event_family")
        or candidate.get("normalized_event_type")
        or ""
    ).strip()


def _lineage_valid(lineage: Mapping[str, Any] | None, raw_path: str | Path | None) -> bool:
    if not isinstance(lineage, Mapping) or not lineage:
        return False
    request_id = str(lineage.get("request_id") or lineage.get("retrieval_id") or lineage.get("producing_request_id") or "").strip()
    captured_at = str(lineage.get("retrieved_at") or lineage.get("captured_at") or lineage.get("requested_at") or "").strip()
    path_value = str(lineage.get("raw_path") or lineage.get("path") or raw_path or "").strip()
    return bool(request_id and captured_at and path_value)


def validate_candidate_bound_tier_b_fallback(
    candidate: Mapping[str, Any],
    *,
    raw_bytes: bytes,
    source_url: str,
    expected_sha256: str,
    raw_path: str | Path,
    retrieval_lineage: Mapping[str, Any] | None,
    caller_official: bool = False,
) -> dict[str, Any]:
    """Validate one Tier-B content fallback without creating a candidate."""
    reasons: list[str] = []
    ticker = str(candidate.get("ticker") or "").strip()
    rule = ISSUER_OFFICIAL_TRUST_REGISTRY.get(ticker)
    identity_tier = str(candidate.get("identity_authority_tier") or candidate.get("source_tier") or "").strip()
    identity_id = str(candidate.get("identity_record_id") or candidate.get("rcept_no") or "").strip()
    rank = candidate.get("identity_candidate_rank", candidate.get("candidate_rank"))
    try:
        rank_value = int(rank)
    except (TypeError, ValueError):
        rank_value = 0
    score = candidate.get("event_match_score", 0)
    try:
        score_value = int(score)
    except (TypeError, ValueError):
        score_value = 0

    caller_asserted_official = caller_official or str(candidate.get("official", "")).strip().lower() == "true"
    if caller_asserted_official:
        reasons.append("CALLER_ASSERTED_OFFICIAL_TRUST_FORBIDDEN")
    if rule is None:
        reasons.append("TICKER_NOT_REGISTERED")
    if identity_tier not in {TIER_A1_OPENDART, TIER_A2_KRX_KIND}:
        reasons.append("A1_A2_IDENTITY_REQUIRED")
    if not identity_id:
        reasons.append("IDENTITY_RECORD_ID_MISSING")
    if rank_value <= 0 or not bool(candidate.get("candidate_rank_deterministic", candidate.get("rank_deterministic", False))):
        reasons.append("CANDIDATE_RANK_NOT_DETERMINISTIC")
    if score_value <= 0:
        reasons.append("EVENT_MATCH_SCORE_NOT_POSITIVE")
    if candidate.get("a1_body_usable", candidate.get("a1_document_body_usable")) is not False:
        reasons.append("A1_DOCUMENT_NOT_PROVEN_UNUSABLE")
    if candidate.get("a1_failure_persisted") is not True:
        reasons.append("A1_FAILURE_NOT_PERSISTED")
    if not str(candidate.get("a1_transport_response_sha256") or "").strip():
        reasons.append("A1_TRANSPORT_HASH_MISSING")
    if candidate.get("a2_candidate_specific_attempted") is not True:
        reasons.append("A2_CANDIDATE_ATTEMPT_MISSING")
    if candidate.get("a2_usable") is True or candidate.get("a2_content_usable") is True:
        reasons.append("A2_USABLE_CONTENT_PRESENT")
    if candidate.get("a1_a2_contradiction") is True:
        reasons.append("A1_A2_CONTRADICTION")
    if rule is not None:
        parsed_url = urlsplit(source_url)
        path = unquote(parsed_url.path or "")
        try:
            exact_port = parsed_url.port in (None, 443)
        except ValueError:
            exact_port = False
        if parsed_url.scheme.lower() != rule.scheme or parsed_url.hostname != rule.host:
            reasons.append("ISSUER_URL_NOT_TRUSTED")
        if parsed_url.username or parsed_url.password or not exact_port:
            reasons.append("ISSUER_URL_AUTHORITY_NOT_EXACT")
        if not path.startswith(rule.path_prefix) or ".." in path.split("/"):
            reasons.append("ISSUER_URL_PATH_NOT_TRUSTED")
        issuer_claim = str(candidate.get("issuer_name") or candidate.get("issuer") or "")
        if _normalize_issuer(issuer_claim) not in {_normalize_issuer(alias) for alias in rule.issuer_aliases}:
            reasons.append("CANDIDATE_ISSUER_NOT_REGISTERED_ALIAS")

    actual_sha = hashlib.sha256(raw_bytes).hexdigest()
    raw_file = Path(raw_path)
    if not raw_file.is_file():
        reasons.append("TIER_B_RAW_MISSING")
    elif raw_file.read_bytes() != raw_bytes:
        reasons.append("TIER_B_RAW_PATH_CONTENT_MISMATCH")
    if not raw_bytes:
        reasons.append("TIER_B_RAW_EMPTY")
    if actual_sha != str(expected_sha256 or "").strip():
        reasons.append("TIER_B_RAW_SHA256_MISMATCH")
    if not _lineage_valid(retrieval_lineage, raw_path):
        reasons.append("RETRIEVAL_LINEAGE_MISSING")

    parsed = parse_issuer_official_document(raw_bytes)
    if not parsed["body_usable"]:
        reasons.append("TIER_B_BODY_UNUSABLE")
    if parsed["blocked_page_detected"]:
        reasons.append("TIER_B_BLOCKED_PAGE")
    if not rule or _normalize_issuer(parsed["parsed_issuer"]) not in {_normalize_issuer(alias) for alias in rule.issuer_aliases}:
        reasons.append("PARSED_ISSUER_MISMATCH")
    if ticker not in parsed["ticker_candidates"]:
        reasons.append("PARSED_TICKER_MISMATCH")
    disclosure_date = _candidate_date(candidate)
    if not disclosure_date or parsed["publication_date"] != disclosure_date:
        reasons.append("DISCLOSURE_DATE_MISMATCH")
    event = _candidate_event(candidate)
    if not event or parsed["event_family"] != event:
        reasons.append("EVENT_FAMILY_MISMATCH")
    report_name = str(candidate.get("report_nm") or candidate.get("report_name") or "")
    if not re.search(r"기재정정|update|amend", report_name, re.IGNORECASE) or parsed["update_semantics"] != "UPDATE":
        reasons.append("UPDATE_SEMANTICS_MISMATCH")
    if parsed["official_anchor_type"] != str(candidate.get("expected_anchor_type") or "NEW_SHARE_LISTING_DATE"):
        reasons.append("TIMING_FIELD_MISMATCH")
    if not parsed["official_anchor_date"] or not parsed["superseded_anchor_date"] or not parsed["chronology_valid"]:
        reasons.append("TIMING_CHRONOLOGY_INVALID")
    if candidate.get("a1_a2_observed_anchor_date") and candidate.get("a1_a2_observed_anchor_date") != parsed["official_anchor_date"]:
        reasons.append("A1_A2_TIMING_CONTRADICTION")

    reasons = list(dict.fromkeys(reasons))
    valid = not reasons
    provenance = {
        "identity_authority_tier": identity_tier,
        "content_authority_tier": TIER_B_ISSUER_OFFICIAL,
        "identity_record_id": identity_id,
        "identity_candidate_rank": rank_value,
        "content_source_url": source_url,
        "content_source_sha256": actual_sha,
        "authority_resolution_mode": CANDIDATE_BOUND_FALLBACK_MODE,
        "fallback_reason": "A1_DOCUMENT_BODY_UNUSABLE_AND_A2_UNAVAILABLE",
    }
    return {
        "valid": valid,
        "reason_codes": reasons,
        "provenance": provenance,
        "parsed": parsed,
        "raw_path": str(raw_path),
        "raw_size_bytes": len(raw_bytes),
        "raw_sha256": actual_sha,
        "trusted_url": not any(code.startswith("ISSUER_URL") for code in reasons),
    }


def trust_registry_audit() -> dict[str, Any]:
    """Return a serialisable, secret-free snapshot of the trust registry."""
    return {
        ticker: {
            "ticker": rule.ticker,
            "issuer_aliases": list(rule.issuer_aliases),
            "allowed_scheme": rule.scheme,
            "allowed_host": rule.host,
            "allowed_path_prefix": rule.path_prefix,
            "wildcard": False,
        }
        for ticker, rule in ISSUER_OFFICIAL_TRUST_REGISTRY.items()
    }
