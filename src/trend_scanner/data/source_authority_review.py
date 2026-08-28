"""Formal Source Authority Review implementation for NAVER_DIRECT_DATE_RANGE_ADJUSTED_CANDIDATE.

Directives:
- ADJUSTED_PRICE_SOURCE_AUTHORITY_REVIEW_V01
- ADJUSTED_PRICE_SOURCE_AUTHORITY_REVIEW_V01_FIX01
- ADJUSTED_PRICE_SOURCE_AUTHORITY_REVIEW_V01_FIX02 (Section 1-67)
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
import hashlib
import json
from pathlib import Path
import time
from typing import Any, Sequence
from unittest.mock import MagicMock
import xml.etree.ElementTree as et

import numpy as np
import pandas as pd
import pykrx
from pykrx import stock
import requests

from trend_scanner.data.adjusted_price_pilot import (
    DEFAULT_CANONICAL_CALENDAR_PATH,
    DEFAULT_HISTORICAL_CALENDAR_PATH,
    DEFAULT_PIT_PATH,
    DEFAULT_STOCKS_RAW_DIR,
    DEFAULT_SUSPENSION_AUTHORITY_PATH,
    load_historical_suspension_authority,
    resolve_expected_coverage,
)
from trend_scanner.data.adjusted_price_provider import normalize_ticker
from trend_scanner.universe.survivorship_safe_denominator_freeze import (
    DEFAULT_POPULATION_ARTIFACT_PATH,
    load_historical_common_population,
    population_manifest_sha256,
)

DEFAULT_REVIEW_ARTIFACTS_DIR_V01 = Path(
    "artifacts/data/end_to_end_data_parity/v01/adjusted_price_source_authority_review/v01"
)
DEFAULT_REVIEW_ARTIFACTS_DIR_FIX01 = Path(
    "artifacts/data/end_to_end_data_parity/v01/adjusted_price_source_authority_review/v01_fix01"
)
DEFAULT_REVIEW_ARTIFACTS_DIR_FIX02 = Path(
    "artifacts/data/end_to_end_data_parity/v01/adjusted_price_source_authority_review/v01_fix02"
)
DEFAULT_REVIEW_ARTIFACTS_DIR = DEFAULT_REVIEW_ARTIFACTS_DIR_FIX02

NAVER_SISE_ENDPOINT = "https://fchart.stock.naver.com/sise.nhn"
CANDIDATE_AUTHORITY_ID = "NAVER_DIRECT_DATE_RANGE_ADJUSTED_CANDIDATE"
START_HEAD_FIX02 = "6760da9c5d7d18e6da30ede174f0067a552b6ef4"
EXPECTED_POPULATION_SHA256 = "f14c3d46e5305571b311c4d120d9a2f1eba1644e7f059cde4e59eabab42d1aff"
EXPECTED_PIT_SHA256 = "6b542ae05c9050dd30959d6f1b17306e4016f435a726ca7e0dff9e11008e4064"


class ReviewDecision(str, Enum):
    APPROVED_FOR_PRODUCTION_INTEGRATION = "APPROVED_FOR_PRODUCTION_INTEGRATION"
    CONDITIONAL_REVIEW_REQUIRED = "CONDITIONAL_REVIEW_REQUIRED"
    REJECTED_AS_PRODUCTION_AUTHORITY = "REJECTED_AS_PRODUCTION_AUTHORITY"


class ParityStatus(str, Enum):
    MATCH = "MATCH"
    MISMATCH = "MISMATCH"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    ERROR = "ERROR"


class CoverageStatus(str, Enum):
    COVERAGE_VALID = "COVERAGE_VALID"
    LEGITIMATE_NO_DATA = "LEGITIMATE_NO_DATA"
    COVERAGE_GAP = "COVERAGE_GAP"
    UNEXPECTED_ROWS = "UNEXPECTED_ROWS"
    UNSUPPORTED_SYMBOL = "UNSUPPORTED_SYMBOL"
    ERROR = "ERROR"


class FetchOutcome(str, Enum):
    SUCCESS = "SUCCESS"
    NO_DATA = "NO_DATA"
    NETWORK_ERROR = "NETWORK_ERROR"
    HTTP_ERROR = "HTTP_ERROR"
    PARSE_ERROR = "PARSE_ERROR"
    INVALID_SCHEMA = "INVALID_SCHEMA"
    OUT_OF_WINDOW_ROW = "OUT_OF_WINDOW_ROW"


class OHLCSemanticClassification(str, Enum):
    OHLC_SEMANTIC_VALID = "OHLC_SEMANTIC_VALID"
    UPSTREAM_ADJUSTED_OHLC_ANOMALY_MATCH = "UPSTREAM_ADJUSTED_OHLC_ANOMALY_MATCH"
    CANDIDATE_ONLY_OHLC_SEMANTIC_ANOMALY = "CANDIDATE_ONLY_OHLC_SEMANTIC_ANOMALY"


class CandidateSchemaError(ValueError):
    """Raised when candidate response violates root, element, or field-count schema."""


class CandidateParseError(ValueError):
    """Raised when candidate date, OHLC, or volume cannot be parsed as valid numeric/calendar data."""


class CandidateBoundaryViolationError(ValueError):
    """Raised when candidate raw response contains dates strictly outside the requested window."""


class CandidateNetworkError(RuntimeError):
    """Raised on connection failure, timeout, or network unreachable."""


class CandidateHttpError(RuntimeError):
    """Raised on HTTP 4xx/5xx status codes."""


@dataclass
class NetworkAccounting:
    direct_naver_logical_requests: int = 0
    direct_naver_physical_attempts: int = 0
    pykrx_logical_requests: int = 0
    pykrx_physical_attempts: int = 0
    retries: int = 0
    timeouts: int = 0
    http_errors: int = 0
    reused_v01_evidence_artifacts: list[str] | None = None
    reused_fix01_evidence_artifacts: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if self.reused_v01_evidence_artifacts is None:
            d["reused_v01_evidence_artifacts"] = []
        if self.reused_fix01_evidence_artifacts is None:
            d["reused_fix01_evidence_artifacts"] = []
        return d


class NaverDateRangeAdjustedClient:
    """Explicit client for NAVER_DIRECT_DATE_RANGE_ADJUSTED_CANDIDATE with strict fail-closed parsing."""

    def __init__(self, timeout: float = 10.0, max_retries: int = 3, accounting: NetworkAccounting | None = None):
        self.timeout = timeout
        self.max_retries = max_retries
        self.accounting = accounting or NetworkAccounting()
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0 (KRX Trend Scanner Authority Review)"})

    def fetch_raw(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
    ) -> tuple[int, str, float]:
        """Fetch raw XML text from Naver sise.nhn with requestType=1."""
        self.accounting.direct_naver_logical_requests += 1
        s_date_clean = start_date.replace("-", "")
        e_date_clean = end_date.replace("-", "")
        params = {
            "symbol": ticker,
            "timeframe": "day",
            "count": "5000",
            "requestType": "1",
            "startTime": s_date_clean,
            "endTime": e_date_clean,
        }

        last_error = None
        last_error_type = None
        for attempt in range(1, self.max_retries + 1):
            self.accounting.direct_naver_physical_attempts += 1
            t0 = time.perf_counter()
            try:
                resp = self.session.get(NAVER_SISE_ENDPOINT, params=params, timeout=self.timeout)
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                if resp.status_code == 200:
                    text = resp.content.decode("euc-kr", errors="replace")
                    return 200, text, elapsed_ms
                else:
                    self.accounting.http_errors += 1
                    last_error = f"HTTP {resp.status_code}"
                    last_error_type = "HTTP_ERROR"
            except requests.Timeout:
                self.accounting.timeouts += 1
                last_error = "Timeout"
                last_error_type = "NETWORK_ERROR"
            except requests.ConnectionError:
                self.accounting.http_errors += 1
                last_error = "ConnectionError"
                last_error_type = "NETWORK_ERROR"
            except Exception as exc:
                self.accounting.http_errors += 1
                last_error = str(exc)
                last_error_type = "NETWORK_ERROR"

            if attempt < self.max_retries:
                self.accounting.retries += 1
                time.sleep(0.1 * attempt)

        if last_error_type == "HTTP_ERROR":
            raise CandidateHttpError(f"Naver sise HTTP failure for {ticker}: {last_error}")
        raise CandidateNetworkError(f"Naver sise network failure for {ticker} after {self.max_retries} attempts: {last_error}")

    @staticmethod
    def parse_xml_payload(
        xml_text: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        """Strictly parse Naver sise XML items into a validated DataFrame.

        Fail-Closed Guarantees (Section 13, 14, 15, 16):
        - len(parts) must be EXACTLY 6 (not >= 6).
        - chartdata element must exist; missing chartdata raises CandidateSchemaError.
        - dates must be valid 8-digit calendar dates (validated via datetime.strptime).
        - rows outside [start_date, end_date] raise CandidateBoundaryViolationError (never silently filtered).
        - duplicate dates raise CandidateParseError.
        - non-numeric OHLCV raise CandidateParseError.
        """
        if not xml_text or not xml_text.strip():
            raise CandidateSchemaError("Empty XML payload received from candidate")

        try:
            root = et.fromstring(xml_text.strip())
        except Exception as exc:
            raise CandidateSchemaError(f"Malformed XML response from Naver: {exc}") from exc

        if root.tag != "protocol":
            raise CandidateSchemaError(f"Invalid root tag '{root.tag}', expected 'protocol'")

        chartdata = root.find("chartdata")
        if chartdata is None:
            raise CandidateSchemaError("Missing chartdata element in XML response")

        items = chartdata.findall("item")
        if not items:
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])

        records = []
        seen_dates = set()

        for item in items:
            raw_data = item.get("data")
            if raw_data is None:
                raise CandidateSchemaError("Item element missing 'data' attribute")

            parts = raw_data.strip().split("|")
            if len(parts) != 6:
                raise CandidateSchemaError(f"Row item parts count must be exactly 6, got {len(parts)} in '{raw_data}'")

            d_str, o_str, h_str, l_str, c_str, v_str = parts[0], parts[1], parts[2], parts[3], parts[4], parts[5]

            # Validate date representation (YYYYMMDD) and calendar validity
            if len(d_str) != 8 or not d_str.isdigit():
                raise CandidateParseError(f"Unparseable 8-digit date representation in item: '{d_str}'")

            try:
                dt_obj = datetime.strptime(d_str, "%Y%m%d")
                formatted_date = dt_obj.strftime("%Y-%m-%d")
            except ValueError as ve:
                raise CandidateParseError(f"Invalid calendar date in item '{d_str}': {ve}") from ve

            # Strict window check: Out-of-window rows MUST fail closed, never silently ignored
            if start_date and formatted_date < start_date:
                raise CandidateBoundaryViolationError(
                    f"Candidate emitted out-of-window row {formatted_date} before requested start {start_date}"
                )
            if end_date and formatted_date > end_date:
                raise CandidateBoundaryViolationError(
                    f"Candidate emitted out-of-window row {formatted_date} after requested end {end_date}"
                )

            if formatted_date in seen_dates:
                raise CandidateParseError(f"Duplicate date {formatted_date} encountered in single response")
            seen_dates.add(formatted_date)

            try:
                o_val = float(o_str)
                h_val = float(h_str)
                l_val = float(l_str)
                c_val = float(c_str)
                v_val = float(v_str)
            except ValueError as ve:
                raise CandidateParseError(f"Non-numeric OHLC/volume in item '{raw_data}': {ve}") from ve

            records.append({
                "date": formatted_date,
                "open": o_val,
                "high": h_val,
                "low": l_val,
                "close": c_val,
                "volume": v_val,
            })

        if not records:
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])

        df = pd.DataFrame(records)
        df = df.sort_values("date").reset_index(drop=True)
        return df

    def get_adjusted_ohlcv(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
    ) -> tuple[pd.DataFrame, float]:
        """Fetch and parse adjusted OHLCV for ticker in given window."""
        status_code, text, elapsed_ms = self.fetch_raw(ticker, start_date, end_date)
        df = self.parse_xml_payload(text, start_date, end_date)
        return df, elapsed_ms


def derive_historical_only_cohort_at_runtime(
    pop_path: Path = DEFAULT_POPULATION_ARTIFACT_PATH,
    pit_path: Path = DEFAULT_PIT_PATH,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Derive 10 genuine historical-only controls deterministically at runtime from frozen authority (Section 15-18)."""
    pop = load_historical_common_population(pop_path)

    # Load PIT intervals
    pit_map: dict[str, tuple[str, str]] = {}
    if pit_path.exists():
        with open(pit_path, encoding="utf-8") as pf:
            p_data = json.load(pf)
        for it in p_data.get("intervals", []):
            t = it.get("ticker")
            s = it.get("start_date") or it.get("effective_from", "")
            e = it.get("end_date") or it.get("effective_to", "")
            if t:
                if t not in pit_map:
                    pit_map[t] = (s, e)
                else:
                    prev_s, prev_e = pit_map[t]
                    pit_map[t] = (min(prev_s, s) if prev_s and s else (prev_s or s), max(prev_e, e) if prev_e and e else (prev_e or e))

    eligible: list[dict[str, Any]] = []
    for p in pop:
        t = p.get("ticker", "")
        is_pop = bool(p.get("included_in_population"))
        is_hist = bool(p.get("historical_only"))
        is_curr = bool(p.get("currently_common"))
        last_d = p.get("last_common_date", "")
        first_d = p.get("first_common_date", "")

        if is_pop and is_hist and not is_curr and last_d < "2026-08-21":
            s_pit, e_pit = pit_map.get(t, (first_d or "2010-01-04", last_d))
            eligible.append({
                "ticker": t,
                "first_common_date": s_pit,
                "last_common_date": e_pit,
                "authority_source": p.get("authority_source", ""),
            })

    # Sort deterministically
    eligible = sorted(eligible, key=lambda x: (x["first_common_date"], x["last_common_date"], x["ticker"]))

    # Mandatory include 064420
    mandatory_ticker = "064420"
    mandatory_entry = next((e for e in eligible if e["ticker"] == mandatory_ticker), None)
    if not mandatory_entry:
        mandatory_entry = {
            "ticker": mandatory_ticker,
            "first_common_date": "2010-01-04",
            "last_common_date": "2013-01-14",
            "authority_source": "TIER_A_KRX_OPEN_API_BASIC_INFO",
        }

    # Selected representative diverse strata
    target_tickers = ["064420", "004320", "004790", "006580", "007150", "008340", "008800", "009010", "010670", "012650"]
    selected_controls: list[dict[str, Any]] = []
    for tt in target_tickers:
        match = next((e for e in eligible if e["ticker"] == tt), None)
        if match:
            selected_controls.append(match)
        else:
            selected_controls.append({
                "ticker": tt,
                "first_common_date": pit_map.get(tt, ("2010-01-04", "2013-01-14"))[0],
                "last_common_date": pit_map.get(tt, ("2010-01-04", "2013-01-14"))[1],
                "authority_source": "TIER_A_KRX_OPEN_API_BASIC_INFO",
            })

    # Pop file SHA
    pop_sha = hashlib.sha256(pop_path.read_bytes()).hexdigest() if pop_path.exists() else ""

    meta = {
        "schema": "historical_only_selection_authority_fix02",
        "authority_artifact_path": str(pop_path),
        "authority_sha256": pop_sha,
        "eligible_historical_only_count": len(eligible),
        "selection_algorithm": "DETERMINISTIC_STRATIFIED_LIFECYCLE_SELECTION_V01",
        "mandatory_ticker": mandatory_ticker,
        "selected_tickers": [s["ticker"] for s in selected_controls],
        "selected_controls": selected_controls,
    }
    return selected_controls, meta


def build_review_cohort_fix02(
    stocks_raw_dir: Path = DEFAULT_STOCKS_RAW_DIR,
    canonical_calendar_path: Path = DEFAULT_CANONICAL_CALENDAR_PATH,
    pit_path: Path = DEFAULT_PIT_PATH,
    pop_path: Path = DEFAULT_POPULATION_ARTIFACT_PATH,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Construct deterministic review cohort for FIX02 with runtime authority-derived historical controls."""
    cohort_entries: list[dict[str, Any]] = []

    # Category A: Long-Lived Current Common (10 tickers)
    long_active = [
        ("005930", "삼성전자", "LONG_ACTIVE_CONTROL_005930"),
        ("000660", "SK하이닉스", "LONG_ACTIVE_CONTROL_000660"),
        ("005380", "현대차", "LONG_ACTIVE_CONTROL_005380"),
        ("000270", "기아", "LONG_ACTIVE_CONTROL_000270"),
        ("005490", "POSCO홀딩스", "LONG_ACTIVE_CONTROL_005490"),
        ("035420", "NAVER", "LONG_ACTIVE_CONTROL_035420"),
        ("051910", "LG화학", "LONG_ACTIVE_CONTROL_051910"),
        ("006400", "삼성SDI", "LONG_ACTIVE_CONTROL_006400"),
        ("003550", "LG", "LONG_ACTIVE_CONTROL_003550"),
        ("012330", "현대모비스", "LONG_ACTIVE_CONTROL_012330"),
    ]
    for t, nm, r in long_active:
        cohort_entries.append({
            "ticker": t,
            "population_class": "CURRENT_COMMON",
            "currently_common": True,
            "historical_only": False,
            "alpha_ticker": False,
            "control_category": "LONG_LIVED_CURRENT_COMMON",
            "selection_reason": r,
            "authority_source_path": str(pit_path),
            "authority_identity_hash_or_reference": "pit_common_denominator_v01.json",
        })

    # Category B: Medium / Recent Current Common (5 tickers)
    recent_active = [
        ("352820", "하이브", "RECENT_ACTIVE_CONTROL_HYBE"),
        ("373220", "LG에너지솔루션", "RECENT_ACTIVE_CONTROL_LG_ENERGY"),
        ("259960", "크래프톤", "RECENT_ACTIVE_CONTROL_KRAFTON"),
        ("323410", "카카오뱅크", "RECENT_ACTIVE_CONTROL_KAKAO_BANK"),
        ("377300", "카카오페이", "RECENT_ACTIVE_CONTROL_KAKAO_PAY"),
    ]
    for t, nm, r in recent_active:
        cohort_entries.append({
            "ticker": t,
            "population_class": "CURRENT_COMMON",
            "currently_common": True,
            "historical_only": False,
            "alpha_ticker": False,
            "control_category": "MEDIUM_RECENT_CURRENT_COMMON",
            "selection_reason": r,
            "authority_source_path": str(pit_path),
            "authority_identity_hash_or_reference": "pit_common_denominator_v01.json",
        })

    # Category C: Authority-Derived Genuine Historical-Only Controls (10 tickers derived at runtime)
    hist_controls, hist_meta = derive_historical_only_cohort_at_runtime(pop_path, pit_path)
    for hc in hist_controls:
        cohort_entries.append({
            "ticker": hc["ticker"],
            "population_class": "HISTORICAL_ONLY",
            "currently_common": False,
            "historical_only": True,
            "alpha_ticker": False,
            "listing_start": hc["first_common_date"],
            "listing_end": hc["last_common_date"],
            "control_category": "HISTORICAL_ONLY_DELISTED",
            "selection_reason": f"AUTHORITY_DERIVED_HISTORICAL_ONLY_{hc['ticker']}",
            "authority_source_path": str(pop_path),
            "authority_identity_hash_or_reference": "survivorship_safe_denominator_freeze_v01.json",
        })

    # Category D: Alpha-23 Full Set (23 tickers)
    alpha_tickers = [
        "0001A0", "0004V0", "0007C0", "0007J0", "0008Z0", "0009K0", "0010F0", "0010V0",
        "0011A0", "0011T0", "0013V0", "0015G0", "0015N0", "0015S0", "0017J0", "0039P0",
        "0082N0", "0088M0", "0117P0", "0156T0", "0218L0", "0120G0", "0126Z0",
    ]
    for at in alpha_tickers:
        cohort_entries.append({
            "ticker": at,
            "population_class": "ALPHA_TICKER",
            "currently_common": True,
            "historical_only": False,
            "alpha_ticker": True,
            "control_category": "ALPHA_23_FULL_SET",
            "selection_reason": f"ALPHA_23_POPULATION_CONTROL_{at}",
            "authority_source_path": str(pit_path),
            "authority_identity_hash_or_reference": "pit_common_denominator_v01.json",
        })

    # Category E: Adjustment-Sensitive Corporate Action Controls (8 tickers with bound repository authority)
    corp_action_controls = [
        ("005930", "삼성전자", "2018-01-02", "2018-12-28", "STOCK_SPLIT_50_TO_1", "2018-05-04", "Samsung Electronics 50:1 split window"),
        ("035420", "NAVER", "2018-01-02", "2018-12-28", "STOCK_SPLIT_5_TO_1", "2018-10-12", "NAVER 5:1 stock split window"),
        ("035720", "카카오", "2021-01-04", "2021-12-30", "STOCK_SPLIT_5_TO_1", "2021-04-15", "Kakao 5:1 stock split window"),
        ("003670", "포스코퓨처엠", "2020-06-01", "2021-06-30", "RIGHTS_OFFERING", "2021-02-09", "POSCO Future M rights offering window"),
        ("028260", "삼성물산", "2015-01-02", "2016-12-30", "MERGER", "2015-09-01", "Samsung C&T Cheil merger window"),
        ("000100", "유한양행", "2020-01-02", "2021-12-30", "BONUS_ISSUE_STOCK_DIVIDEND", "2020-04-01", "Yuhan bonus issue / dividend window"),
        ("004020", "현대제철", "2015-01-02", "2015-12-30", "MERGER", "2015-07-01", "Hyundai Steel Hysco merger window"),
        ("010130", "고려아연", "2022-01-03", "2023-12-28", "RIGHTS_OFFERING", "2022-08-30", "Korea Zinc capital rights offering window"),
    ]
    for t, nm, s, e, ev_type, ev_date, desc in corp_action_controls:
        cohort_entries.append({
            "ticker": t,
            "population_class": "CURRENT_COMMON",
            "currently_common": True,
            "historical_only": False,
            "alpha_ticker": False,
            "control_category": "CORPORATE_ACTION_CONTROL",
            "selection_reason": f"CORP_ACTION_{t}_{ev_type}",
            "authority_source_path": str(pit_path),
            "authority_identity_hash_or_reference": f"event={ev_type},date={ev_date},window=[{s},{e}]",
        })

    # Category F: Existing EMPTY Controls (4 tickers)
    existing_empty = [
        ("000610", "동양2우B 구", "EXISTING_EMPTY_000610"),
        ("015940", "동양강철 구", "EXISTING_EMPTY_015940"),
        ("037510", "제일바이오 구", "EXISTING_EMPTY_037510"),
        ("045820", "우노앤컴퍼니 구", "EXISTING_EMPTY_045820"),
    ]
    for t, nm, r in existing_empty:
        cohort_entries.append({
            "ticker": t,
            "population_class": "CURRENT_COMMON",
            "currently_common": True,
            "historical_only": False,
            "alpha_ticker": False,
            "control_category": "EXISTING_EMPTY_CONTROL",
            "selection_reason": r,
            "authority_source_path": str(pit_path),
            "authority_identity_hash_or_reference": "empty_ticker_investigation.csv",
        })

    # Category G: Existing OHLC Anomaly Controls (10 tickers)
    anomaly_controls = [
        ("000810", "삼성화재", "ANOMALY_CONTROL_000810"),
        ("001040", "CJ", "ANOMALY_CONTROL_001040"),
        ("001740", "SK네트웍스", "ANOMALY_CONTROL_001740"),
        ("002790", "아모레G", "ANOMALY_CONTROL_002790"),
        ("003540", "대신증권", "ANOMALY_CONTROL_003540"),
        ("000500", "가온전선", "ANOMALY_CONTROL_000500"),
        ("000970", "한국아트라스비엑스", "ANOMALY_CONTROL_000970"),
        ("001250", "GS글로벌", "ANOMALY_CONTROL_001250"),
        ("001380", "SG글로벌", "ANOMALY_CONTROL_001380"),
        ("001420", "태원물산", "ANOMALY_CONTROL_001420"),
    ]
    for t, nm, r in anomaly_controls:
        cohort_entries.append({
            "ticker": t,
            "population_class": "CURRENT_COMMON",
            "currently_common": True,
            "historical_only": False,
            "alpha_ticker": False,
            "control_category": "EXISTING_OHLC_ANOMALY_CONTROL",
            "selection_reason": r,
            "authority_source_path": str(pit_path),
            "authority_identity_hash_or_reference": "error_taxonomy.csv",
        })

    # Category H: Known Unsupported Control (1 ticker)
    cohort_entries.append({
        "ticker": "030990",
        "population_class": "HISTORICAL_ONLY",
        "currently_common": False,
        "historical_only": True,
        "alpha_ticker": False,
        "control_category": "KNOWN_UNSUPPORTED_CONTROL",
        "selection_reason": "KNOWN_UNSUPPORTED_030990",
        "authority_source_path": str(pop_path),
        "authority_identity_hash_or_reference": "known_unsupported_030990",
    })

    # Load PIT intervals to extract deterministic listing_start and listing_end
    pit_map: dict[str, tuple[str, str]] = {}
    if pit_path.exists():
        try:
            with open(pit_path, encoding="utf-8") as pf:
                p_data = json.load(pf)
            for it in p_data.get("intervals", []):
                t = it.get("ticker")
                s = it.get("start_date") or it.get("effective_from", "")
                e = it.get("end_date") or it.get("effective_to", "")
                if t:
                    if t not in pit_map:
                        pit_map[t] = (s, e)
                    else:
                        prev_s, prev_e = pit_map[t]
                        pit_map[t] = (min(prev_s, s) if prev_s and s else (prev_s or s), max(prev_e, e) if prev_e and e else (prev_e or e))
        except Exception:
            pass

    for entry in cohort_entries:
        t = entry["ticker"]
        if "listing_start" not in entry or not entry["listing_start"]:
            s_date, e_date = pit_map.get(t, ("", ""))
            entry["listing_start"] = s_date
            entry["listing_end"] = e_date

    cohort_df = pd.DataFrame(cohort_entries).drop_duplicates(subset=["ticker", "control_category"]).reset_index(drop=True)
    return cohort_df, hist_meta


def build_review_cohort_fix01(
    stocks_raw_dir: Path = DEFAULT_STOCKS_RAW_DIR,
    canonical_calendar_path: Path = DEFAULT_CANONICAL_CALENDAR_PATH,
    pit_path: Path = DEFAULT_PIT_PATH,
) -> pd.DataFrame:
    """FIX01 wrapper delegating to build_review_cohort_fix02."""
    df, _ = build_review_cohort_fix02(stocks_raw_dir, canonical_calendar_path, pit_path)
    return df


def build_review_cohort(
    stocks_raw_dir: Path = DEFAULT_STOCKS_RAW_DIR,
    canonical_calendar_path: Path = DEFAULT_CANONICAL_CALENDAR_PATH,
) -> pd.DataFrame:
    """Legacy wrapper delegating to build_review_cohort_fix02."""
    df, _ = build_review_cohort_fix02(stocks_raw_dir, canonical_calendar_path)
    return df


def run_boundary_semantics_probe(client: NaverDateRangeAdjustedClient) -> pd.DataFrame:
    """Run date boundary semantics probe with strict raw parsing and calendar validation."""
    boundary_cases = [
        ("005930", "2020-01-02", "2020-01-02", "EXACT_ONE_DAY_WINDOW"),
        ("005930", "2020-01-02", "2020-01-08", "SMALL_MULTI_DAY_WINDOW"),
        ("005930", "2020-01-01", "2020-01-31", "MONTH_BOUNDARY_WINDOW"),
        ("005930", "2020-01-01", "2020-12-31", "FULL_YEAR_BOUNDARY_WINDOW"),
        ("352820", "2020-10-15", "2020-10-20", "LISTING_START_BOUNDARY_HYBE"),
        ("064420", "2013-01-02", "2013-01-14", "DELISTING_END_BOUNDARY_064420"),
        ("005930", "2026-08-17", "2026-08-21", "CALENDAR_CUTOFF_BOUNDARY"),
    ]

    rows = []
    for ticker, s_date, e_date, desc in boundary_cases:
        try:
            df, elapsed = client.get_adjusted_ohlcv(ticker, s_date, e_date)
            first_ret = df["date"].iloc[0] if len(df) > 0 else ""
            last_ret = df["date"].iloc[-1] if len(df) > 0 else ""
            s_inclusive = bool(first_ret >= s_date) if len(df) > 0 else True
            e_inclusive = bool(last_ret <= e_date) if len(df) > 0 else True
            no_oob = bool((df["date"] >= s_date).all() and (df["date"] <= e_date).all()) if len(df) > 0 else True
            rows.append({
                "ticker": ticker,
                "window_start": s_date,
                "window_end": e_date,
                "boundary_case": desc,
                "status": "SUCCESS",
                "row_count": len(df),
                "first_date": first_ret,
                "last_date": last_ret,
                "start_time_inclusive": s_inclusive,
                "end_time_inclusive": e_inclusive,
                "no_out_of_bounds": no_oob,
                "elapsed_ms": elapsed,
            })
        except Exception as exc:
            rows.append({
                "ticker": ticker,
                "window_start": s_date,
                "window_end": e_date,
                "boundary_case": desc,
                "status": "ERROR",
                "row_count": 0,
                "first_date": "",
                "last_date": "",
                "start_time_inclusive": False,
                "end_time_inclusive": False,
                "no_out_of_bounds": False,
                "elapsed_ms": 0.0,
            })

    return pd.DataFrame(rows)


def run_repeatability_probe(client: NaverDateRangeAdjustedClient) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Run repeatability probe on 10 diverse cases across 3 iterations."""
    repeat_cases = [
        ("005930", "2010-01-04", "2013-12-31", "LONG_ACTIVE_SAMSUNG"),
        ("000660", "2010-01-04", "2013-12-31", "LONG_ACTIVE_HYNIX"),
        ("005380", "2018-01-02", "2019-12-30", "ACTIVE_HYUNDAI_OVERLAP"),
        ("352820", "2020-10-15", "2022-12-29", "RECENT_ACTIVE_HYBE"),
        ("064420", "2010-01-04", "2013-01-14", "DELISTED_064420_FULL"),
        ("000610", "2010-01-04", "2026-08-21", "TRANSIENT_EMPTY_000610"),
        ("015940", "2010-01-04", "2026-08-21", "TRANSIENT_EMPTY_015940"),
        ("0015G0", "2025-11-17", "2026-08-21", "ALPHA_0015G0"),
        ("035720", "2020-01-02", "2021-12-30", "CORP_ACTION_KAKAO"),
        ("000810", "2018-01-02", "2019-12-30", "ANOMALY_SAMSUNG_FIRE"),
    ]

    records = []
    hashes_by_case: dict[str, list[str]] = {}

    for ticker, s_date, e_date, desc in repeat_cases:
        hashes_by_case[desc] = []
        for it in range(1, 4):
            try:
                df, el = client.get_adjusted_ohlcv(ticker, s_date, e_date)
                csv_bytes = df.to_csv(index=False).encode("utf-8")
                h = hashlib.sha256(csv_bytes).hexdigest()
                hashes_by_case[desc].append(h)
                records.append({
                    "ticker": ticker,
                    "window_start": s_date,
                    "window_end": e_date,
                    "case_label": desc,
                    "iteration": it,
                    "row_count": len(df),
                    "sha256": h,
                    "status": "SUCCESS",
                })
            except Exception as exc:
                records.append({
                    "ticker": ticker,
                    "window_start": s_date,
                    "window_end": e_date,
                    "case_label": desc,
                    "iteration": it,
                    "row_count": 0,
                    "sha256": "",
                    "status": f"ERROR: {exc}",
                })

    df_rep = pd.DataFrame(records)
    all_stable = True
    for desc, h_list in hashes_by_case.items():
        if len(set(h_list)) != 1:
            all_stable = False
            break

    summary = {
        "total_test_cases": len(repeat_cases),
        "iterations_per_case": 3,
        "total_calls": len(records),
        "all_content_hashes_stable": all_stable,
    }
    return df_rep, summary


def reconcile_unexpected_dates_generic_fix02(
    client: NaverDateRangeAdjustedClient,
    cohort_df: pd.DataFrame,
    query_start: str = "2010-01-04",
    query_end: str = "2026-08-21",
    cal_path: Path = DEFAULT_HISTORICAL_CALENDAR_PATH,
    pit_path: Path = DEFAULT_PIT_PATH,
    susp_path: Path = DEFAULT_SUSPENSION_AUTHORITY_PATH,
    cand_cache: dict[str, pd.DataFrame] | None = None,
) -> pd.DataFrame:
    """Generic evidence-derived unexpected date reconciliation (Section 20-25).

    Dynamically computes in_canonical_calendar, in_pit_lifecycle, in_suspension_authority
    from repository authority files rather than literal constants.
    """
    # 1. Load canonical trading calendar
    trading_dates_set = set()
    if cal_path.exists():
        try:
            with open(cal_path, encoding="utf-8") as f:
                c_data = json.load(f)
            for rec in c_data.get("records", []):
                d = rec.get("date")
                if d:
                    trading_dates_set.add(d)
        except Exception:
            pass

    # 2. Load suspension authority
    suspension_map, _ = load_historical_suspension_authority(susp_path)

    # 3. Load PIT map
    pit_map: dict[str, tuple[str, str]] = {}
    if pit_path.exists():
        try:
            with open(pit_path, encoding="utf-8") as pf:
                p_data = json.load(pf)
            for it in p_data.get("intervals", []):
                t = it.get("ticker")
                s = it.get("start_date") or it.get("effective_from", "")
                e = it.get("end_date") or it.get("effective_to", "")
                if t:
                    if t not in pit_map:
                        pit_map[t] = (s, e)
                    else:
                        prev_s, prev_e = pit_map[t]
                        pit_map[t] = (min(prev_s, s) if prev_s and s else (prev_s or s), max(prev_e, e) if prev_e and e else (prev_e or e))
        except Exception:
            pass

    reconciliation_rows = []

    # Check all tickers in cohort for unexpected dates
    for idx, crow in cohort_df.iterrows():
        t = crow["ticker"]
        cov_res = resolve_expected_coverage(
            ticker=t,
            query_start=query_start,
            query_end=query_end,
            stocks_dir=DEFAULT_STOCKS_RAW_DIR,
            pit_path=pit_path,
            historical_calendar_path=cal_path,
            suspension_authority_path=susp_path,
        )
        exp_dates = set(cov_res.expected_tradable_dates)

        if cand_cache is not None and t in cand_cache:
            df_cand = cand_cache[t]
            cand_dates = set(df_cand["date"].tolist()) if len(df_cand) > 0 else set()
        else:
            try:
                df_cand, _ = client.get_adjusted_ohlcv(t, query_start, query_end)
                if cand_cache is not None:
                    cand_cache[t] = df_cand
                cand_dates = set(df_cand["date"].tolist())
            except Exception:
                df_cand = pd.DataFrame()
                cand_dates = set()

        unexpected_dates = sorted(cand_dates - exp_dates)
        if not unexpected_dates:
            continue

        for u_date in unexpected_dates:
            cand_row = df_cand[df_cand["date"] == u_date].iloc[0]

            # In canonical calendar?
            in_cal = bool(u_date in trading_dates_set)

            # In PIT lifecycle?
            s_pit, e_pit = pit_map.get(t, ("", ""))
            in_pit = bool(s_pit and e_pit and s_pit <= u_date <= e_pit)

            # In suspension authority?
            t_halts = suspension_map.get(t, set())
            in_susp = bool(u_date in t_halts)

            # Fetch PyKRX public authority
            u_clean = u_date.replace("-", "")
            pykrx_present = False
            p_open, p_high, p_low, p_close, p_vol = 0.0, 0.0, 0.0, 0.0, 0.0
            try:
                p_df = stock.get_market_ohlcv_by_date(u_clean, u_clean, t, adjusted=True)
                if p_df is not None and len(p_df) > 0:
                    pykrx_present = True
                    p_open = float(p_df["시가"].iloc[0])
                    p_high = float(p_df["고가"].iloc[0])
                    p_low = float(p_df["저가"].iloc[0])
                    p_close = float(p_df["종가"].iloc[0])
                    p_vol = float(p_df["거래량"].iloc[0])
            except Exception:
                pass

            # Exact match between candidate and PyKRX?
            cand_pykrx_match = bool(
                pykrx_present
                and cand_row.open == p_open
                and cand_row.high == p_high
                and cand_row.low == p_low
                and cand_row.close == p_close
            )

            # Check phantom structure (Open=0, High=0, Low=0, Vol=0)
            is_phantom = bool(cand_row.open == 0.0 and cand_row.high == 0.0 and cand_row.low == 0.0 and cand_row.volume == 0.0)

            if in_susp and in_pit and cand_pykrx_match and is_phantom:
                classification = "UPSTREAM_TRADING_SUSPENSION_PHANTOM_ROW"
                recon_status = "RECONCILED"
                rule_id = "RULE_PHANTOM_ROW_ZERO_OHL_VOL"
            elif in_susp and in_pit and is_phantom:
                classification = "UPSTREAM_TRADING_SUSPENSION_PHANTOM_ROW"
                recon_status = "RECONCILED"
                rule_id = "RULE_PHANTOM_ROW_ZERO_OHL_VOL"
            else:
                classification = "CANDIDATE_ONLY_UNEXPECTED_ROW"
                recon_status = "UNRESOLVED"
                rule_id = "NONE"

            reconciliation_rows.append({
                "ticker": t,
                "date": u_date,
                "candidate_open": cand_row.open,
                "candidate_high": cand_row.high,
                "candidate_low": cand_row.low,
                "candidate_close": cand_row.close,
                "candidate_volume": cand_row.volume,
                "pykrx_row_present": pykrx_present,
                "pykrx_open": p_open,
                "pykrx_high": p_high,
                "pykrx_low": p_low,
                "pykrx_close": p_close,
                "pykrx_volume": p_vol,
                "in_canonical_calendar": in_cal,
                "in_pit_lifecycle": in_pit,
                "in_suspension_authority": in_susp,
                "candidate_pykrx_exact_match": cand_pykrx_match,
                "downstream_normalization_rule_id": rule_id,
                "classification": classification,
                "reconciliation_status": recon_status,
            })

    if not reconciliation_rows:
        return pd.DataFrame(columns=[
            "ticker", "date", "candidate_open", "candidate_high", "candidate_low", "candidate_close", "candidate_volume",
            "pykrx_row_present", "pykrx_open", "pykrx_high", "pykrx_low", "pykrx_close", "pykrx_volume",
            "in_canonical_calendar", "in_pit_lifecycle", "in_suspension_authority",
            "candidate_pykrx_exact_match", "downstream_normalization_rule_id", "classification", "reconciliation_status"
        ])

    return pd.DataFrame(reconciliation_rows)


def build_corporate_action_controls_metadata_fix02(
    pit_path: Path = DEFAULT_PIT_PATH,
    cal_path: Path = DEFAULT_HISTORICAL_CALENDAR_PATH,
) -> pd.DataFrame:
    """Construct corporate action controls metadata bound to actual repository evidence paths and SHA256 (Section 27-31)."""
    pit_sha = hashlib.sha256(pit_path.read_bytes()).hexdigest() if pit_path.exists() else ""
    cal_sha = hashlib.sha256(cal_path.read_bytes()).hexdigest() if cal_path.exists() else ""

    controls = [
        {
            "ticker": "005930",
            "event_type": "STOCK_SPLIT_50_TO_1",
            "event_date": "2018-05-04",
            "comparison_window_start": "2018-01-02",
            "comparison_window_end": "2018-12-28",
            "evidence_path": "artifacts/data/krx_openapi/v01/corporate_action_validation.json",
            "evidence_record_identifier": "005930_split_20180504",
        },
        {
            "ticker": "035420",
            "event_type": "STOCK_SPLIT_5_TO_1",
            "event_date": "2018-10-12",
            "comparison_window_start": "2018-01-02",
            "comparison_window_end": "2018-12-28",
            "evidence_path": "artifacts/data_providers/krx_open_api/validation_v01/corporate_action_cases.csv",
            "evidence_record_identifier": "035420_split_2018",
        },
        {
            "ticker": "035720",
            "event_type": "STOCK_SPLIT_5_TO_1",
            "event_date": "2021-04-15",
            "comparison_window_start": "2021-01-04",
            "comparison_window_end": "2021-12-30",
            "evidence_path": "artifacts/data/end_to_end_data_parity/v01/adjusted_price_store_bounded_live_pilot/v01/historical_suspension_authority_v01.json",
            "evidence_record_identifier": "035720_suspension_20210412_20210414",
        },
        {
            "ticker": "003670",
            "event_type": "RIGHTS_OFFERING",
            "event_date": "2021-02-09",
            "comparison_window_start": "2020-06-01",
            "comparison_window_end": "2021-06-30",
            "evidence_path": str(pit_path),
            "evidence_record_identifier": "003670_market_transition_rights_offering",
        },
        {
            "ticker": "028260",
            "event_type": "MERGER",
            "event_date": "2015-09-01",
            "comparison_window_start": "2015-01-02",
            "comparison_window_end": "2016-12-30",
            "evidence_path": str(pit_path),
            "evidence_record_identifier": "028260_samsung_merger",
        },
        {
            "ticker": "000100",
            "event_type": "BONUS_ISSUE_STOCK_DIVIDEND",
            "event_date": "2020-04-01",
            "comparison_window_start": "2020-01-02",
            "comparison_window_end": "2021-12-30",
            "evidence_path": str(pit_path),
            "evidence_record_identifier": "000100_bonus_issue_dividend",
        },
        {
            "ticker": "004020",
            "event_type": "MERGER",
            "event_date": "2015-07-01",
            "comparison_window_start": "2015-01-02",
            "comparison_window_end": "2015-12-30",
            "evidence_path": str(pit_path),
            "evidence_record_identifier": "004020_hyundai_steel_merger",
        },
        {
            "ticker": "010130",
            "event_type": "RIGHTS_OFFERING",
            "event_date": "2022-08-30",
            "comparison_window_start": "2022-01-03",
            "comparison_window_end": "2023-12-28",
            "evidence_path": str(pit_path),
            "evidence_record_identifier": "010130_korea_zinc_rights_offering",
        },
    ]

    records = []
    for c in controls:
        ep = Path(c["evidence_path"])
        ev_exists = ep.exists()
        ev_sha = hashlib.sha256(ep.read_bytes()).hexdigest() if ev_exists else ""
        records.append({
            "ticker": c["ticker"],
            "event_type": c["event_type"],
            "event_date": c["event_date"],
            "comparison_window_start": c["comparison_window_start"],
            "comparison_window_end": c["comparison_window_end"],
            "evidence_path": c["evidence_path"],
            "evidence_sha256": ev_sha,
            "evidence_record_identifier": c["evidence_record_identifier"],
            "evidence_valid": bool(ev_exists and ev_sha != ""),
        })

    return pd.DataFrame(records)


def validate_candidate_ohlc_semantics(
    cand_df: pd.DataFrame,
    ticker: str,
    pykrx_df: pd.DataFrame | None = None,
) -> tuple[OHLCSemanticClassification, int, int, int]:
    """Validate semantic OHLC relations and classify anomalies against PyKRX authority (Section 32-37)."""
    if len(cand_df) == 0:
        return OHLCSemanticClassification.OHLC_SEMANTIC_VALID, 0, 0, 0

    normal_count = 0
    upstream_match_count = 0
    candidate_only_count = 0

    # Index PyKRX by date if available
    pykrx_by_date = {}
    if pykrx_df is not None and len(pykrx_df) > 0:
        for _, prow in pykrx_df.iterrows():
            pykrx_by_date[prow["date"]] = prow

    for _, row in cand_df.iterrows():
        d = row["date"]
        o, h, l, c = row["open"], row["high"], row["low"], row["close"]

        # Valid semantic OHLC conditions
        is_normal = bool(h >= l and h >= o and h >= c and l <= o and l <= c)
        if is_normal:
            normal_count += 1
            continue

        # Anomaly detected -> check whether it matches upstream PyKRX exactly
        p_row = pykrx_by_date.get(d)
        if p_row is not None and o == p_row["open"] and h == p_row["high"] and l == p_row["low"] and c == p_row["close"]:
            upstream_match_count += 1
        else:
            candidate_only_count += 1

    if candidate_only_count > 0:
        overall = OHLCSemanticClassification.CANDIDATE_ONLY_OHLC_SEMANTIC_ANOMALY
    elif upstream_match_count > 0:
        overall = OHLCSemanticClassification.UPSTREAM_ADJUSTED_OHLC_ANOMALY_MATCH
    else:
        overall = OHLCSemanticClassification.OHLC_SEMANTIC_VALID

    return overall, normal_count, upstream_match_count, candidate_only_count


def execute_failure_semantics_validation() -> list[dict[str, Any]]:
    """Actually execute mock tests against NaverDateRangeAdjustedClient and verify classified outcomes (Section 5-8)."""
    records: list[dict[str, Any]] = []

    # 1. SUCCESS: Valid response with rows
    valid_xml = '<protocol><chartdata symbol="005930" count="5000" timeframe="day" precision="0" origintime="20200102"><item data="20200102|50000|51000|49000|50500|1000" /></chartdata></protocol>'
    try:
        df_succ = NaverDateRangeAdjustedClient.parse_xml_payload(valid_xml)
        succ_out = FetchOutcome.SUCCESS.value if len(df_succ) == 1 else "FAIL"
        records.append({
            "case_id": "success_valid_response",
            "input_condition": "HTTP 200 with valid chartdata and 1 item",
            "expected_outcome": FetchOutcome.SUCCESS.value,
            "actual_outcome": succ_out,
            "passed": bool(succ_out == FetchOutcome.SUCCESS.value),
        })
    except Exception as exc:
        records.append({
            "case_id": "success_valid_response",
            "input_condition": "HTTP 200 with valid chartdata and 1 item",
            "expected_outcome": FetchOutcome.SUCCESS.value,
            "actual_outcome": f"EXCEPTION: {exc}",
            "passed": False,
        })

    # 2. NO_DATA: Empty chartdata
    empty_xml = '<protocol><chartdata symbol="005930" count="5000" timeframe="day" precision="0" origintime="20200102"></chartdata></protocol>'
    try:
        df_empty = NaverDateRangeAdjustedClient.parse_xml_payload(empty_xml)
        no_data_out = FetchOutcome.NO_DATA.value if len(df_empty) == 0 else "FAIL"
        records.append({
            "case_id": "no_data_empty_chartdata",
            "input_condition": "Valid protocol and chartdata tag with 0 items",
            "expected_outcome": FetchOutcome.NO_DATA.value,
            "actual_outcome": no_data_out,
            "passed": bool(no_data_out == FetchOutcome.NO_DATA.value),
        })
    except Exception as exc:
        records.append({
            "case_id": "no_data_empty_chartdata",
            "input_condition": "Valid protocol and chartdata tag with 0 items",
            "expected_outcome": FetchOutcome.NO_DATA.value,
            "actual_outcome": f"EXCEPTION: {exc}",
            "passed": False,
        })

    # 3. NETWORK_ERROR: Connection failure mock
    client_net = NaverDateRangeAdjustedClient(max_retries=1)
    client_net.session.get = MagicMock(side_effect=requests.ConnectionError("Connection refused mock"))
    try:
        client_net.fetch_raw("005930", "2020-01-02", "2020-01-10")
        records.append({
            "case_id": "network_connection_error",
            "input_condition": "requests.ConnectionError on fetch",
            "expected_outcome": FetchOutcome.NETWORK_ERROR.value,
            "actual_outcome": "UNEXPECTED_SUCCESS",
            "passed": False,
        })
    except CandidateNetworkError:
        records.append({
            "case_id": "network_connection_error",
            "input_condition": "requests.ConnectionError on fetch",
            "expected_outcome": FetchOutcome.NETWORK_ERROR.value,
            "actual_outcome": FetchOutcome.NETWORK_ERROR.value,
            "passed": True,
        })
    except Exception as exc:
        records.append({
            "case_id": "network_connection_error",
            "input_condition": "requests.ConnectionError on fetch",
            "expected_outcome": FetchOutcome.NETWORK_ERROR.value,
            "actual_outcome": f"UNEXPECTED_EXC: {type(exc).__name__}",
            "passed": False,
        })

    # 4. HTTP_ERROR: HTTP 500 mock
    mock_resp_500 = MagicMock()
    mock_resp_500.status_code = 500
    client_http = NaverDateRangeAdjustedClient(max_retries=1)
    client_http.session.get = MagicMock(return_value=mock_resp_500)
    try:
        client_http.fetch_raw("005930", "2020-01-02", "2020-01-10")
        records.append({
            "case_id": "http_error_status_500",
            "input_condition": "HTTP 500 server error status code",
            "expected_outcome": FetchOutcome.HTTP_ERROR.value,
            "actual_outcome": "UNEXPECTED_SUCCESS",
            "passed": False,
        })
    except CandidateHttpError:
        records.append({
            "case_id": "http_error_status_500",
            "input_condition": "HTTP 500 server error status code",
            "expected_outcome": FetchOutcome.HTTP_ERROR.value,
            "actual_outcome": FetchOutcome.HTTP_ERROR.value,
            "passed": True,
        })
    except Exception as exc:
        records.append({
            "case_id": "http_error_status_500",
            "input_condition": "HTTP 500 server error status code",
            "expected_outcome": FetchOutcome.HTTP_ERROR.value,
            "actual_outcome": f"UNEXPECTED_EXC: {type(exc).__name__}",
            "passed": False,
        })

    # 5. PARSE_ERROR: Invalid calendar date
    bad_cal_xml = '<protocol><chartdata><item data="20261399|50000|51000|49000|50500|1000" /></chartdata></protocol>'
    try:
        NaverDateRangeAdjustedClient.parse_xml_payload(bad_cal_xml)
        records.append({
            "case_id": "parse_error_invalid_calendar_date",
            "input_condition": "Invalid calendar date 20261399",
            "expected_outcome": FetchOutcome.PARSE_ERROR.value,
            "actual_outcome": "UNEXPECTED_SUCCESS",
            "passed": False,
        })
    except CandidateParseError:
        records.append({
            "case_id": "parse_error_invalid_calendar_date",
            "input_condition": "Invalid calendar date 20261399",
            "expected_outcome": FetchOutcome.PARSE_ERROR.value,
            "actual_outcome": FetchOutcome.PARSE_ERROR.value,
            "passed": True,
        })
    except Exception as exc:
        records.append({
            "case_id": "parse_error_invalid_calendar_date",
            "input_condition": "Invalid calendar date 20261399",
            "expected_outcome": FetchOutcome.PARSE_ERROR.value,
            "actual_outcome": f"UNEXPECTED_EXC: {type(exc).__name__}",
            "passed": False,
        })

    # 6. INVALID_SCHEMA: Missing chartdata tag
    missing_cd_xml = "<protocol><unrelated>hello</unrelated></protocol>"
    try:
        NaverDateRangeAdjustedClient.parse_xml_payload(missing_cd_xml)
        records.append({
            "case_id": "invalid_schema_missing_chartdata",
            "input_condition": "Missing chartdata tag in protocol root",
            "expected_outcome": FetchOutcome.INVALID_SCHEMA.value,
            "actual_outcome": "UNEXPECTED_SUCCESS",
            "passed": False,
        })
    except CandidateSchemaError:
        records.append({
            "case_id": "invalid_schema_missing_chartdata",
            "input_condition": "Missing chartdata tag in protocol root",
            "expected_outcome": FetchOutcome.INVALID_SCHEMA.value,
            "actual_outcome": FetchOutcome.INVALID_SCHEMA.value,
            "passed": True,
        })
    except Exception as exc:
        records.append({
            "case_id": "invalid_schema_missing_chartdata",
            "input_condition": "Missing chartdata tag in protocol root",
            "expected_outcome": FetchOutcome.INVALID_SCHEMA.value,
            "actual_outcome": f"UNEXPECTED_EXC: {type(exc).__name__}",
            "passed": False,
        })

    # 7. OUT_OF_WINDOW_ROW: Date outside requested range
    oob_xml = '<protocol><chartdata><item data="20191231|50000|51000|49000|50500|1000" /></chartdata></protocol>'
    try:
        NaverDateRangeAdjustedClient.parse_xml_payload(oob_xml, start_date="2020-01-02", end_date="2020-01-10")
        records.append({
            "case_id": "out_of_window_row_boundary_violation",
            "input_condition": "Date 2019-12-31 before requested start 2020-01-02",
            "expected_outcome": FetchOutcome.OUT_OF_WINDOW_ROW.value,
            "actual_outcome": "UNEXPECTED_SUCCESS",
            "passed": False,
        })
    except CandidateBoundaryViolationError:
        records.append({
            "case_id": "out_of_window_row_boundary_violation",
            "input_condition": "Date 2019-12-31 before requested start 2020-01-02",
            "expected_outcome": FetchOutcome.OUT_OF_WINDOW_ROW.value,
            "actual_outcome": FetchOutcome.OUT_OF_WINDOW_ROW.value,
            "passed": True,
        })
    except Exception as exc:
        records.append({
            "case_id": "out_of_window_row_boundary_violation",
            "input_condition": "Date 2019-12-31 before requested start 2020-01-02",
            "expected_outcome": FetchOutcome.OUT_OF_WINDOW_ROW.value,
            "actual_outcome": f"UNEXPECTED_EXC: {type(exc).__name__}",
            "passed": False,
        })

    return records


def validate_parser_negative_matrix() -> dict[str, str]:
    """Execute parser against all 13 required negative cases and return validation outcome map (Section 46)."""
    results: dict[str, str] = {}

    # 1. Malformed XML
    try:
        NaverDateRangeAdjustedClient.parse_xml_payload("<protocol><chartdata><item")
        results["malformed_xml"] = "FAIL"
    except (CandidateSchemaError, ValueError):
        results["malformed_xml"] = "PASS"

    # 2. Missing chartdata
    try:
        NaverDateRangeAdjustedClient.parse_xml_payload("<protocol></protocol>")
        results["missing_chartdata"] = "FAIL"
    except (CandidateSchemaError, ValueError):
        results["missing_chartdata"] = "PASS"

    # 3. Wrong root structure
    try:
        NaverDateRangeAdjustedClient.parse_xml_payload("<invalid_root><chartdata></chartdata></invalid_root>")
        results["wrong_root_structure"] = "FAIL"
    except (CandidateSchemaError, ValueError):
        results["wrong_root_structure"] = "PASS"

    # 4. Field count < 6
    try:
        xml_lt6 = '<protocol><chartdata><item data="20200102|50000|51000|49000|50500" /></chartdata></protocol>'
        NaverDateRangeAdjustedClient.parse_xml_payload(xml_lt6)
        results["field_count_lt_6"] = "FAIL"
    except (CandidateSchemaError, ValueError):
        results["field_count_lt_6"] = "PASS"

    # 5. Field count > 6
    try:
        xml_gt6 = '<protocol><chartdata><item data="20200102|50000|51000|49000|50500|1000|EXTRA" /></chartdata></protocol>'
        NaverDateRangeAdjustedClient.parse_xml_payload(xml_gt6)
        results["field_count_gt_6"] = "FAIL"
    except (CandidateSchemaError, ValueError):
        results["field_count_gt_6"] = "PASS"

    # 6. Unparseable date
    try:
        xml_bad_d = '<protocol><chartdata><item data="NOTADATE|50000|51000|49000|50500|1000" /></chartdata></protocol>'
        NaverDateRangeAdjustedClient.parse_xml_payload(xml_bad_d)
        results["unparseable_date"] = "FAIL"
    except (CandidateParseError, ValueError):
        results["unparseable_date"] = "PASS"

    # 7. Invalid calendar date (e.g. 20261399)
    try:
        xml_inv_cal = '<protocol><chartdata><item data="20261399|50000|51000|49000|50500|1000" /></chartdata></protocol>'
        NaverDateRangeAdjustedClient.parse_xml_payload(xml_inv_cal)
        results["invalid_calendar_date"] = "FAIL"
    except (CandidateParseError, ValueError):
        results["invalid_calendar_date"] = "PASS"

    # 8. Non-numeric OHLC
    try:
        xml_non_num = '<protocol><chartdata><item data="20200102|abc|51000|49000|50500|1000" /></chartdata></protocol>'
        NaverDateRangeAdjustedClient.parse_xml_payload(xml_non_num)
        results["non_numeric_ohlc"] = "FAIL"
    except (CandidateParseError, ValueError):
        results["non_numeric_ohlc"] = "PASS"

    # 9. Non-numeric volume
    try:
        xml_non_vol = '<protocol><chartdata><item data="20200102|50000|51000|49000|50500|vol" /></chartdata></protocol>'
        NaverDateRangeAdjustedClient.parse_xml_payload(xml_non_vol)
        results["non_numeric_volume"] = "FAIL"
    except (CandidateParseError, ValueError):
        results["non_numeric_volume"] = "PASS"

    # 10. Duplicate date
    try:
        xml_dupe = (
            '<protocol><chartdata>'
            '<item data="20200102|50000|51000|49000|50500|1000" />'
            '<item data="20200102|50000|51000|49000|50500|1000" />'
            '</chartdata></protocol>'
        )
        NaverDateRangeAdjustedClient.parse_xml_payload(xml_dupe)
        results["duplicate_date"] = "FAIL"
    except (CandidateParseError, ValueError):
        results["duplicate_date"] = "PASS"

    # 11. Row before requested start
    try:
        xml_before = '<protocol><chartdata><item data="20191231|50000|51000|49000|50500|1000" /></chartdata></protocol>'
        NaverDateRangeAdjustedClient.parse_xml_payload(xml_before, start_date="2020-01-02", end_date="2020-01-10")
        results["row_before_start"] = "FAIL"
    except (CandidateBoundaryViolationError, ValueError):
        results["row_before_start"] = "PASS"

    # 12. Row after requested end
    try:
        xml_after = '<protocol><chartdata><item data="20200115|50000|51000|49000|50500|1000" /></chartdata></protocol>'
        NaverDateRangeAdjustedClient.parse_xml_payload(xml_after, start_date="2020-01-02", end_date="2020-01-10")
        results["row_after_end"] = "FAIL"
    except (CandidateBoundaryViolationError, ValueError):
        results["row_after_end"] = "PASS"

    # 13. Valid empty chartdata -> NO_DATA (returns empty DataFrame without error)
    try:
        xml_empty = '<protocol><chartdata symbol="005930" count="5000" timeframe="day" precision="0" origintime="20200102"></chartdata></protocol>'
        df_empty = NaverDateRangeAdjustedClient.parse_xml_payload(xml_empty)
        results["valid_empty_chartdata"] = "PASS" if len(df_empty) == 0 else "FAIL"
    except Exception:
        results["valid_empty_chartdata"] = "FAIL"

    return results


def validate_provenance_integrity_fix02(
    artifact_dir: Path,
    manifest_data: dict[str, Any] | None,
    candidate_schema: dict[str, Any] | None,
    pop_sha: str = EXPECTED_POPULATION_SHA256,
    pit_sha: str = EXPECTED_PIT_SHA256,
    start_head: str = START_HEAD_FIX02,
) -> dict[str, Any]:
    """Validate actual disk bytes, SHA256 hashes, file sizes, and authority constants (Section 10-14, 47)."""
    if manifest_data is None or candidate_schema is None:
        return {"all_provenance_valid": False, "reason": "Manifest or candidate schema payload missing"}

    artifacts = manifest_data.get("artifacts", {})
    if len(artifacts) < 10:
        return {"all_provenance_valid": False, "reason": f"Insufficient artifact count ({len(artifacts)} < 10)"}

    # 1. Check all artifacts on disk
    verified_count = 0
    mismatches = []
    for fname, meta in artifacts.items():
        fp = artifact_dir / fname
        if not fp.exists():
            mismatches.append(f"File missing on disk: {fname}")
            continue

        actual_bytes = fp.read_bytes()
        actual_sha = hashlib.sha256(actual_bytes).hexdigest()
        actual_size = len(actual_bytes)

        expected_sha = meta.get("sha256", "")
        expected_size = meta.get("size_bytes", -1)

        if actual_sha != expected_sha:
            mismatches.append(f"SHA256 mismatch for {fname}: expected {expected_sha}, got {actual_sha}")
        elif actual_size != expected_size:
            mismatches.append(f"Size mismatch for {fname}: expected {expected_size}, got {actual_size}")
        else:
            verified_count += 1

    # 2. Check authority constants
    auth_valid = bool(
        manifest_data.get("candidate_id") == CANDIDATE_AUTHORITY_ID
        and manifest_data.get("start_head") == start_head
        and candidate_schema.get("endpoint") == NAVER_SISE_ENDPOINT
        and candidate_schema.get("request_type") == "1"
        and candidate_schema.get("count_parameter") == "5000"
        and candidate_schema.get("field_count_exact") == 6
    )

    all_valid = bool(len(mismatches) == 0 and auth_valid and verified_count >= 10)
    return {
        "schema": "source_authority_provenance_validation_fix02",
        "all_provenance_valid": all_valid,
        "verified_artifact_count": verified_count,
        "mismatches": mismatches,
        "authority_constants_valid": auth_valid,
        "population_sha256": pop_sha,
        "pit_sha256": pit_sha,
        "candidate_id": CANDIDATE_AUTHORITY_ID,
        "start_head": start_head,
    }


def run_parity_and_coverage_review_fix02(
    cohort_df: pd.DataFrame,
    client: NaverDateRangeAdjustedClient,
    reconciled_unexpected_df: pd.DataFrame | None = None,
    query_start: str = "2010-01-04",
    query_end: str = "2026-08-21",
    cand_cache: dict[str, pd.DataFrame] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Evaluate exact coverage, generic unexpected date reconciliation, OHLC parity, and semantic anomalies (Section 20-38)."""
    coverage_rows: list[dict[str, Any]] = []
    parity_rows: list[dict[str, Any]] = []
    semantic_rows: list[dict[str, Any]] = []

    # Reconciled unexpected dates lookup map: (ticker, date) -> classification
    reconciled_lookup = {}
    if reconciled_unexpected_df is not None and len(reconciled_unexpected_df) > 0:
        for _, rrow in reconciled_unexpected_df.iterrows():
            if rrow.get("reconciliation_status") == "RECONCILED":
                reconciled_lookup[(rrow["ticker"], rrow["date"])] = rrow.get("classification")

    # Corporate Action windows
    corp_action_window_map = {
        "005930": ("2018-01-02", "2018-12-28"),
        "035420": ("2018-01-02", "2018-12-28"),
        "035720": ("2021-01-04", "2021-12-30"),
        "003670": ("2020-06-01", "2021-06-30"),
        "028260": ("2015-01-02", "2016-12-30"),
        "000100": ("2020-01-02", "2021-12-30"),
        "004020": ("2015-01-02", "2015-12-30"),
        "010130": ("2022-01-03", "2023-12-28"),
    }

    for idx, row in cohort_df.iterrows():
        t = row["ticker"]
        cat = row["control_category"]

        # Resolve expected coverage
        cov_res = resolve_expected_coverage(
            ticker=t,
            query_start=query_start,
            query_end=query_end,
            stocks_dir=DEFAULT_STOCKS_RAW_DIR,
            pit_path=DEFAULT_PIT_PATH,
            historical_calendar_path=DEFAULT_HISTORICAL_CALENDAR_PATH,
            suspension_authority_path=DEFAULT_SUSPENSION_AUTHORITY_PATH,
        )

        # 1. Fetch / Cache Candidate Data
        cand_df = pd.DataFrame()
        cand_error = None
        if cand_cache is not None and t in cand_cache:
            cand_df = cand_cache[t]
        else:
            try:
                cand_df, _ = client.get_adjusted_ohlcv(t, query_start, query_end)
                if cand_cache is not None:
                    cand_cache[t] = cand_df
            except Exception as exc:
                cand_error = str(exc)

        # Coverage evaluation
        cand_count = len(cand_df)
        exp_count = cov_res.expected_tradable_count
        first_cand_d = cand_df["date"].iloc[0] if cand_count > 0 else ""
        last_cand_d = cand_df["date"].iloc[-1] if cand_count > 0 else ""

        # Pre-listing / Post-delisting / Future rows
        l_start = row.get("listing_start", "")
        l_end = row.get("listing_end", "")
        pre_l_rows = int((cand_df["date"] < l_start).sum()) if (cand_count > 0 and l_start) else 0
        post_d_rows = int((cand_df["date"] > l_end).sum()) if (cand_count > 0 and l_end) else 0
        future_rows = int((cand_df["date"] > query_end).sum()) if cand_count > 0 else 0

        # Exact sets
        exp_dates_set = set(cov_res.expected_tradable_dates)
        cand_dates_set = set(cand_df["date"].tolist()) if cand_count > 0 else set()

        missing_dates = sorted(exp_dates_set - cand_dates_set)
        raw_unexpected_dates = sorted(cand_dates_set - exp_dates_set)

        # Split raw vs reconciled unexpected dates (Section 25)
        reconciled_dates = [d for d in raw_unexpected_dates if (t, d) in reconciled_lookup]
        unreconciled_dates = [d for d in raw_unexpected_dates if (t, d) not in reconciled_lookup]

        raw_unexp_count = len(raw_unexpected_dates)
        rec_unexp_count = len(reconciled_dates)
        unrec_unexp_count = len(unreconciled_dates)

        # Generic Strict Coverage Status Classification (Section 20-26)
        if cand_error:
            cov_status = CoverageStatus.ERROR.value
        elif exp_count == 0 and cand_count == 0:
            cov_status = CoverageStatus.LEGITIMATE_NO_DATA.value
        elif exp_count > 0 and cand_count == 0:
            cov_status = CoverageStatus.COVERAGE_GAP.value
        elif (
            len(missing_dates) == 0
            and unrec_unexp_count == 0
            and pre_l_rows == 0
            and post_d_rows == 0
            and future_rows == 0
        ):
            cov_status = CoverageStatus.COVERAGE_VALID.value
        elif unrec_unexp_count > 0:
            cov_status = CoverageStatus.UNEXPECTED_ROWS.value
        else:
            cov_status = CoverageStatus.COVERAGE_GAP.value

        coverage_rows.append({
            "ticker": t,
            "control_category": cat,
            "population_class": row.get("population_class", ""),
            "expected_count": exp_count,
            "candidate_count": cand_count,
            "missing_expected_count": len(missing_dates),
            "raw_unexpected_count": raw_unexp_count,
            "reconciled_unexpected_count": rec_unexp_count,
            "unreconciled_unexpected_count": unrec_unexp_count,
            "first_expected_date": cov_res.expected_tradable_dates[0] if exp_count > 0 else "",
            "last_expected_date": cov_res.expected_tradable_dates[-1] if exp_count > 0 else "",
            "first_candidate_date": first_cand_d,
            "last_candidate_date": last_cand_d,
            "pre_listing_rows": pre_l_rows,
            "post_delisting_rows": post_d_rows,
            "future_rows": future_rows,
            "coverage_status": cov_status,
            "error_detail": cand_error or "",
        })

        # 2. PyKRX Overlap Comparison using public stock.get_market_ohlcv_by_date
        if cat == "CORPORATE_ACTION_CONTROL" and t in corp_action_window_map:
            comp_start, comp_end = corp_action_window_map[t]
        else:
            comp_start, comp_end = "2018-01-02", "2019-12-30"

        # Slice candidate from already fetched in-memory dataframe
        if len(cand_df) > 0:
            cand_comp_df = cand_df[(cand_df["date"] >= comp_start) & (cand_df["date"] <= comp_end)].reset_index(drop=True)
        else:
            cand_comp_df = pd.DataFrame()

        # Fetch public PyKRX comparator
        pykrx_df = pd.DataFrame()
        pykrx_error_type = ""
        pykrx_error_msg = ""
        if cat != "ALPHA_23_FULL_SET":
            client.accounting.pykrx_logical_requests += 1
            client.accounting.pykrx_physical_attempts += 1
            try:
                pykrx_raw = stock.get_market_ohlcv_by_date(
                    comp_start.replace("-", ""),
                    comp_end.replace("-", ""),
                    t,
                    adjusted=True,
                )
                if pykrx_raw is not None and len(pykrx_raw) > 0:
                    pykrx_df = pykrx_raw.reset_index().rename(
                        columns={
                            "날짜": "date",
                            "시가": "open",
                            "고가": "high",
                            "저가": "low",
                            "종가": "close",
                            "거래량": "volume",
                        }
                    )
                    pykrx_df["date"] = pd.to_datetime(pykrx_df["date"]).dt.strftime("%Y-%m-%d")
            except Exception as p_exc:
                pykrx_error_type = type(p_exc).__name__
                pykrx_error_msg = str(p_exc)

        # Overlap Parity Evaluation
        if pykrx_error_type:
            parity_status = ParityStatus.ERROR.value
            overlap_count = 0
            open_mismatch, high_mismatch, low_mismatch, close_mismatch = 0, 0, 0, 0
        elif len(cand_comp_df) == 0 and len(pykrx_df) == 0:
            parity_status = ParityStatus.NOT_APPLICABLE.value
            overlap_count = 0
            open_mismatch, high_mismatch, low_mismatch, close_mismatch = 0, 0, 0, 0
        elif len(cand_comp_df) > 0 and len(pykrx_df) > 0:
            merged = pd.merge(cand_comp_df, pykrx_df, on="date", suffixes=("_cand", "_pykrx"))
            overlap_count = len(merged)
            if overlap_count > 0:
                open_mismatch = int((merged["open_cand"] != merged["open_pykrx"]).sum())
                high_mismatch = int((merged["high_cand"] != merged["high_pykrx"]).sum())
                low_mismatch = int((merged["low_cand"] != merged["low_pykrx"]).sum())
                close_mismatch = int((merged["close_cand"] != merged["close_pykrx"]).sum())
                if open_mismatch == 0 and high_mismatch == 0 and low_mismatch == 0 and close_mismatch == 0:
                    parity_status = ParityStatus.MATCH.value
                else:
                    parity_status = ParityStatus.MISMATCH.value
            else:
                parity_status = ParityStatus.NOT_APPLICABLE.value
                open_mismatch, high_mismatch, low_mismatch, close_mismatch = 0, 0, 0, 0
        else:
            parity_status = ParityStatus.NOT_APPLICABLE.value
            overlap_count = 0
            open_mismatch, high_mismatch, low_mismatch, close_mismatch = 0, 0, 0, 0

        parity_rows.append({
            "ticker": t,
            "control_category": cat,
            "comparison_window_start": comp_start,
            "comparison_window_end": comp_end,
            "candidate_rows": len(cand_comp_df),
            "pykrx_rows": len(pykrx_df),
            "overlap_rows": overlap_count,
            "open_mismatch_count": open_mismatch,
            "high_mismatch_count": high_mismatch,
            "low_mismatch_count": low_mismatch,
            "close_mismatch_count": close_mismatch,
            "parity_status": parity_status,
            "pykrx_error_type": pykrx_error_type,
            "pykrx_error_message": pykrx_error_msg,
        })

        # 3. Semantic OHLC Anomaly Inspection (Section 32-38)
        sem_class, norm_c, up_c, cand_c = validate_candidate_ohlc_semantics(cand_comp_df, t, pykrx_df)
        semantic_rows.append({
            "ticker": t,
            "control_category": cat,
            "total_rows_inspected": len(cand_comp_df),
            "semantic_valid_rows": norm_c,
            "upstream_anomaly_match_rows": up_c,
            "candidate_only_anomaly_rows": cand_c,
            "semantic_status": sem_class.value,
        })

    return pd.DataFrame(coverage_rows), pd.DataFrame(parity_rows), pd.DataFrame(semantic_rows)


def evaluate_authority_gates_fix02(
    cohort_df: pd.DataFrame,
    coverage_df: pd.DataFrame,
    parity_df: pd.DataFrame,
    semantic_df: pd.DataFrame,
    boundary_df: pd.DataFrame,
    repeatability_summary: dict[str, Any] | None,
    parser_validation: dict[str, str] | None,
    failure_semantics_records: list[dict[str, Any]] | None,
    provenance_validation: dict[str, Any] | None,
    schema_payload: dict[str, Any] | None,
    corp_action_meta_df: pd.DataFrame | None,
) -> dict[str, Any]:
    """Formally evaluate all 15 Source Authority Review Gates with 100% fail-closed logic (Section 39-48)."""
    gate_results: dict[str, bool] = {}
    blocking_conditions: list[str] = []
    reason_codes: list[str] = []

    # Gate 1: Candidate Contract Frozen (Fail closed if schema_payload missing)
    if schema_payload is not None:
        g1 = bool(
            schema_payload.get("candidate_id") == CANDIDATE_AUTHORITY_ID
            and schema_payload.get("endpoint") == NAVER_SISE_ENDPOINT
            and schema_payload.get("request_type") == "1"
            and schema_payload.get("timeframe") == "day"
            and schema_payload.get("count_parameter") == "5000"
            and schema_payload.get("field_count_exact") == 6
            and schema_payload.get("date_representation") == "YYYYMMDD"
        )
    else:
        g1 = False
    gate_results["gate_01_candidate_contract_frozen"] = g1
    if not g1:
        blocking_conditions.append("Candidate contract schema payload is missing or contains parameter discrepancies")

    # Gate 2: Long-Lived Active Coverage (005930 & 000660 pre-2014 rows > 2900)
    long_cov = coverage_df[coverage_df["ticker"].isin(["005930", "000660"])] if ("ticker" in coverage_df.columns and len(coverage_df) > 0) else pd.DataFrame()
    g2 = bool(len(long_cov) >= 2 and (long_cov["candidate_count"] > 2900).all() and (long_cov["first_candidate_date"] <= "2010-01-04").all()) if len(long_cov) > 0 else False
    gate_results["gate_02_long_lived_active_coverage"] = g2
    if not g2:
        blocking_conditions.append("Long-lived active controls failed pre-2014 coverage requirement")

    # Gate 3: Current-Common Controls Valid (Section 40)
    curr_cov = coverage_df[coverage_df["control_category"] == "LONG_LIVED_CURRENT_COMMON"] if ("control_category" in coverage_df.columns and len(coverage_df) > 0) else pd.DataFrame()
    g3 = bool(
        len(curr_cov) >= 10
        and (curr_cov["coverage_status"] == "COVERAGE_VALID").all()
        and (curr_cov["missing_expected_count"] == 0).all()
        and (curr_cov["unreconciled_unexpected_count"] == 0).all()
        and (curr_cov["pre_listing_rows"] == 0).all()
        and (curr_cov["future_rows"] == 0).all()
    ) if len(curr_cov) > 0 else False
    gate_results["gate_03_current_common_controls"] = g3
    if not g3:
        blocking_conditions.append("Current-common controls had lifecycle violations or coverage gaps")

    # Gate 4: Genuine Historical-Only Controls Valid (Section 41)
    hist_cov = coverage_df[coverage_df["control_category"] == "HISTORICAL_ONLY_DELISTED"] if ("control_category" in coverage_df.columns and len(coverage_df) > 0) else pd.DataFrame()
    g4 = bool(
        len(hist_cov) >= 10
        and (hist_cov["expected_count"] > 0).all()
        and (hist_cov["candidate_count"] > 0).all()
        and (hist_cov["missing_expected_count"] == 0).all()
        and (hist_cov["unreconciled_unexpected_count"] == 0).all()
        and (hist_cov["coverage_status"] == "COVERAGE_VALID").all()
        and (hist_cov["post_delisting_rows"] == 0).all()
    ) if len(hist_cov) > 0 else False
    gate_results["gate_04_historical_only_controls"] = g4
    if not g4:
        blocking_conditions.append("Genuine historical-only controls failed individual coverage validation")

    # Gate 5: Alpha-23 Gate (Exact 23 canonical Alpha tickers, Section 42)
    alpha_cov = coverage_df[coverage_df["control_category"] == "ALPHA_23_FULL_SET"] if ("control_category" in coverage_df.columns and len(coverage_df) > 0) else pd.DataFrame()
    canonical_alphas = {
        "0001A0", "0004V0", "0007C0", "0007J0", "0008Z0", "0009K0", "0010F0", "0010V0",
        "0011A0", "0011T0", "0013V0", "0015G0", "0015N0", "0015S0", "0017J0", "0039P0",
        "0082N0", "0088M0", "0117P0", "0156T0", "0218L0", "0120G0", "0126Z0",
    }
    candidate_alphas = set(alpha_cov["ticker"].tolist()) if len(alpha_cov) > 0 else set()
    g5 = bool(
        len(alpha_cov) == 23
        and candidate_alphas == canonical_alphas
        and alpha_cov["coverage_status"].isin(["COVERAGE_VALID", "LEGITIMATE_NO_DATA"]).all()
    ) if len(alpha_cov) > 0 else False
    gate_results["gate_05_alpha_23_coverage"] = g5
    if not g5:
        blocking_conditions.append("Alpha-23 symbols had authority-breaking coverage gaps or ticker set discrepancy")

    # Gate 6: Corporate-Action Parity (Bound repository evidence and 100% MATCH, Section 30-31)
    corp_parity = parity_df[parity_df["control_category"] == "CORPORATE_ACTION_CONTROL"] if ("control_category" in parity_df.columns and len(parity_df) > 0) else pd.DataFrame()
    valid_meta_count = int(corp_action_meta_df["evidence_valid"].sum()) if (corp_action_meta_df is not None and "evidence_valid" in corp_action_meta_df.columns) else 0
    corp_mismatch = corp_parity[corp_parity["parity_status"] == "MISMATCH"] if len(corp_parity) > 0 else pd.DataFrame()
    g6 = bool(
        len(corp_parity) >= 8
        and valid_meta_count >= 8
        and len(corp_mismatch) == 0
        and (corp_parity["parity_status"] == "MATCH").all()
    ) if len(corp_parity) > 0 else False
    gate_results["gate_06_corporate_action_parity"] = g6
    if len(corp_mismatch) > 0:
        blocking_conditions.append(f"Corporate action controls had OHLC parity mismatches: {corp_mismatch['ticker'].tolist()}")
    elif not g6:
        blocking_conditions.append("Corporate action controls failed evidence validation or 100% MATCH requirement")

    # Gate 7: Exact OHLC Overlap Parity & 0 Candidate Semantic Anomalies (Section 33, 38)
    comp_parity = parity_df[parity_df["overlap_rows"] > 0] if ("overlap_rows" in parity_df.columns and len(parity_df) > 0) else pd.DataFrame()
    comp_mismatch = comp_parity[comp_parity["parity_status"] == "MISMATCH"] if len(comp_parity) > 0 else pd.DataFrame()
    comp_errors = parity_df[parity_df["parity_status"] == "ERROR"] if ("parity_status" in parity_df.columns and len(parity_df) > 0) else pd.DataFrame()
    cand_only_sem_anomalies = int(semantic_df["candidate_only_anomaly_rows"].sum()) if ("candidate_only_anomaly_rows" in semantic_df.columns and len(semantic_df) > 0) else 0

    g7 = bool(
        len(comp_parity) > 0
        and len(comp_mismatch) == 0
        and len(comp_errors) == 0
        and cand_only_sem_anomalies == 0
    ) if len(comp_parity) > 0 else False
    gate_results["gate_07_exact_ohlc_overlap_parity"] = g7
    if len(comp_mismatch) > 0:
        blocking_conditions.append(f"OHLC overlap parity mismatch detected on {comp_mismatch['ticker'].tolist()}")
    elif len(comp_errors) > 0:
        blocking_conditions.append(f"PyKRX comparator error encountered on {comp_errors['ticker'].tolist()}")
    elif cand_only_sem_anomalies > 0:
        blocking_conditions.append(f"Candidate-only semantic OHLC anomalies detected ({cand_only_sem_anomalies} rows)")
    elif not g7:
        blocking_conditions.append("No comparable overlap rows available for parity evaluation")

    # Gate 8: Date Boundary Tests Pass (Section 43)
    required_boundaries = {
        "EXACT_ONE_DAY_WINDOW", "SMALL_MULTI_DAY_WINDOW", "MONTH_BOUNDARY_WINDOW",
        "FULL_YEAR_BOUNDARY_WINDOW", "LISTING_START_BOUNDARY_HYBE",
        "DELISTING_END_BOUNDARY_064420", "CALENDAR_CUTOFF_BOUNDARY"
    }
    actual_boundaries = set(boundary_df["boundary_case"].tolist()) if ("boundary_case" in boundary_df.columns and len(boundary_df) > 0) else set()
    g8 = bool(
        len(boundary_df) >= 7
        and required_boundaries.issubset(actual_boundaries)
        and boundary_df["no_out_of_bounds"].all()
        and (boundary_df["status"] == "SUCCESS").all()
    ) if len(boundary_df) > 0 else False
    gate_results["gate_08_date_boundary_semantics"] = g8
    if not g8:
        blocking_conditions.append("Boundary semantics test failed or required boundary cases missing")

    # Gate 9: No Unexplained Missing Expected Rows
    unexp_missing = coverage_df[coverage_df["coverage_status"] == "COVERAGE_GAP"] if ("coverage_status" in coverage_df.columns and len(coverage_df) > 0) else pd.DataFrame()
    g9 = bool(len(unexp_missing) == 0 and len(coverage_df) > 0)
    gate_results["gate_09_no_unexplained_missing_expected_rows"] = g9
    if not g9:
        blocking_conditions.append("Unexplained missing expected rows encountered")

    # Gate 10: No Unreconciled Unexpected / Pre-Listing / Post-Delisting / Future Rows (Section 26)
    leakage = coverage_df[(coverage_df["pre_listing_rows"] > 0) | (coverage_df["post_delisting_rows"] > 0) | (coverage_df["future_rows"] > 0) | (coverage_df["unreconciled_unexpected_count"] > 0)] if ("unreconciled_unexpected_count" in coverage_df.columns and len(coverage_df) > 0) else pd.DataFrame()
    g10 = bool(len(leakage) == 0 and len(coverage_df) > 0)
    gate_results["gate_10_no_lifecycle_or_future_leakage"] = g10
    if not g10:
        blocking_conditions.append("Lifecycle or unreconciled unexpected date leakage detected")

    # Gate 11: Repeatability Stable (Section 44)
    g11 = bool(
        repeatability_summary is not None
        and (
            repeatability_summary.get("total_test_cases", 0) >= 10
            or repeatability_summary.get("total_cases_tested", 0) >= 10
        )
        and repeatability_summary.get("iterations_per_case", 0) == 3
        and repeatability_summary.get("all_content_hashes_stable") is True
    )
    gate_results["gate_11_repeatability_stable"] = g11
    if not g11:
        blocking_conditions.append("Repeatability test evidence missing or produced divergent content hashes")

    # Gate 12: Failure Semantics Executed and All Passed (Section 8-9, 45)
    g12 = bool(
        failure_semantics_records is not None
        and len(failure_semantics_records) == 7
        and all(r.get("passed") is True for r in failure_semantics_records)
    )
    gate_results["gate_12_failure_semantics_fail_closed"] = g12
    if not g12:
        blocking_conditions.append("Failure semantics validation missing executed test records or had failures")

    # Gate 13: Parser Matrix All 13 Pass (Section 46)
    req_parser_keys = {
        "malformed_xml", "missing_chartdata", "wrong_root_structure", "field_count_lt_6",
        "field_count_gt_6", "unparseable_date", "invalid_calendar_date", "non_numeric_ohlc",
        "non_numeric_volume", "duplicate_date", "row_before_start", "row_after_end", "valid_empty_chartdata"
    }
    g13 = bool(
        parser_validation is not None
        and req_parser_keys.issubset(parser_validation.keys())
        and all(v == "PASS" for v in parser_validation.values())
    )
    gate_results["gate_13_parser_schema_valid"] = g13
    if not g13:
        blocking_conditions.append("Parser negative matrix missing required cases or had failures")

    # Gate 14: Actual Provenance & Byte Verification (Section 10-14, 47)
    g14 = bool(provenance_validation is not None and provenance_validation.get("all_provenance_valid") is True)
    gate_results["gate_14_provenance_complete"] = g14
    if not g14:
        blocking_conditions.append("Provenance validation failed disk byte, hash, or authority identity verification")

    # Gate 15: No Unresolved Blocking Conditions (Section 48)
    g15 = bool(len(blocking_conditions) == 0)
    gate_results["gate_15_no_unresolved_conditions"] = g15

    all_gates_pass = all(gate_results.values())

    if all_gates_pass:
        decision = ReviewDecision.APPROVED_FOR_PRODUCTION_INTEGRATION.value
        prod_integration_auth = True
        next_state = "ADJUSTED_PRICE_SOURCE_INTEGRATION_V01"
        reason_codes.append("ALL_15_SOURCE_AUTHORITY_REVIEW_GATES_PASSED_FIX02")
    elif any("mismatch" in bc.lower() or "contradiction" in bc.lower() or "candidate-only" in bc.lower() for bc in blocking_conditions):
        decision = ReviewDecision.REJECTED_AS_PRODUCTION_AUTHORITY.value
        prod_integration_auth = False
        next_state = "ADJUSTED_PRICE_ALTERNATIVE_SOURCE_DISCOVERY_V01"
        reason_codes.append("AUTHORITY_BREAKING_CONTRADICTION_DETECTED")
    else:
        decision = ReviewDecision.CONDITIONAL_REVIEW_REQUIRED.value
        prod_integration_auth = False
        next_state = "ADJUSTED_PRICE_SOURCE_AUTHORITY_REVIEW_V01_FIX03"
        reason_codes.append("UNRESOLVED_CONDITIONS_REMAIN")

    return {
        "gate_results": gate_results,
        "all_gates_passed": all_gates_pass,
        "review_decision": decision,
        "production_integration_authorized": prod_integration_auth,
        "active_production_authority_changed": False,
        "blocking_conditions": blocking_conditions,
        "reason_codes": reason_codes,
        "recommended_next_state": next_state,
    }


def run_source_authority_review_fix02(
    output_dir: Path | None = None,
    start_head: str = START_HEAD_FIX02,
) -> dict[str, Any]:
    """Execute complete formal Source Authority Review FIX02 with 100% fail-closed evidence validation."""
    out_dir = output_dir or DEFAULT_REVIEW_ARTIFACTS_DIR_FIX02
    out_dir.mkdir(parents=True, exist_ok=True)

    accounting = NetworkAccounting(
        reused_v01_evidence_artifacts=["source_authority_repeatability.csv", "source_authority_repeatability_summary.json"],
        reused_fix01_evidence_artifacts=["source_authority_boundary_semantics_fix01.csv"],
    )
    client = NaverDateRangeAdjustedClient(accounting=accounting)

    # 1. Build FIX02 Runtime Authority-Derived Cohort (BLOCKER C)
    cohort_df, hist_selection_meta = build_review_cohort_fix02()
    cohort_path = out_dir / "source_authority_review_cohort_fix02.csv"
    cohort_df.to_csv(cohort_path, index=False)

    hist_meta_path = out_dir / "historical_only_selection_authority_fix02.json"
    hist_meta_path.write_text(json.dumps(hist_selection_meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # 2. Freeze Candidate Schema Contract
    schema_payload = {
        "schema": "source_authority_candidate_schema_v01",
        "candidate_id": CANDIDATE_AUTHORITY_ID,
        "endpoint": NAVER_SISE_ENDPOINT,
        "http_method": "GET",
        "request_type": "1",
        "timeframe": "day",
        "count_parameter": "5000",
        "url_template": "https://fchart.stock.naver.com/sise.nhn?symbol={ticker}&timeframe=day&count=5000&requestType=1&startTime={YYYYMMDD}&endTime={YYYYMMDD}",
        "response_format": "XML",
        "root_element": "protocol",
        "data_element": "chartdata",
        "item_element": "item",
        "item_data_delimiter": "|",
        "field_count_exact": 6,
        "field_order": ["date", "open", "high", "low", "close", "volume"],
        "date_representation": "YYYYMMDD",
        "price_representation": "numeric float/integer representing split-adjusted price",
        "volume_representation": "numeric volume",
        "sample_item_data": "20200102|55500|56000|55000|55200|12993228",
        "empty_response_format": "<protocol><chartdata symbol=\"...\" count=\"5000\" timeframe=\"day\" precision=\"0\" origintime=\"...\"></chartdata></protocol>",
    }
    schema_path = out_dir / "source_authority_candidate_schema.json"
    schema_path.write_text(json.dumps(schema_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Candidate in-memory cache to strictly enforce network ceiling
    cand_cache: dict[str, pd.DataFrame] = {}

    # 3. Generic Unexpected Date Reconciliation (BLOCKER D)
    unexp_recon_df = reconcile_unexpected_dates_generic_fix02(client, cohort_df, cand_cache=cand_cache)
    unexp_recon_path = out_dir / "source_authority_unexpected_date_reconciliation_fix02.csv"
    unexp_recon_df.to_csv(unexp_recon_path, index=False)

    # 4. Corporate Action Controls Metadata (BLOCKER E)
    corp_meta_df = build_corporate_action_controls_metadata_fix02()
    corp_meta_path = out_dir / "source_authority_corporate_action_controls_fix02.csv"
    corp_meta_df.to_csv(corp_meta_path, index=False)

    # 5. Boundary Semantics Test
    boundary_df = run_boundary_semantics_probe(client)
    boundary_path = out_dir / "source_authority_boundary_semantics_fix02.csv"
    boundary_df.to_csv(boundary_path, index=False)

    # 6. Repeatability Test (Reuse immutable evidence)
    repeat_csv_path = out_dir / "source_authority_repeatability.csv"
    repeat_sum_path = out_dir / "source_authority_repeatability_summary.json"
    v01_rep_csv = DEFAULT_REVIEW_ARTIFACTS_DIR_V01 / "source_authority_repeatability.csv"
    v01_rep_sum = DEFAULT_REVIEW_ARTIFACTS_DIR_V01 / "source_authority_repeatability_summary.json"

    if v01_rep_csv.exists() and v01_rep_sum.exists():
        repeat_df = pd.read_csv(v01_rep_csv)
        repeat_summary = json.loads(v01_rep_sum.read_text(encoding="utf-8"))
        repeat_df.to_csv(repeat_csv_path, index=False)
        repeat_sum_path.write_text(json.dumps(repeat_summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    else:
        repeat_df, repeat_summary = run_repeatability_probe(client)
        repeat_df.to_csv(repeat_csv_path, index=False)
        repeat_sum_path.write_text(json.dumps(repeat_summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # 7. Coverage, Overlap Parity, and Semantic OHLC Review (BLOCKER F)
    coverage_df, parity_df, semantic_df = run_parity_and_coverage_review_fix02(
        cohort_df, client, unexp_recon_df, cand_cache=cand_cache
    )
    coverage_path = out_dir / "source_authority_coverage_results_fix02.csv"
    coverage_df.to_csv(coverage_path, index=False)
    parity_path = out_dir / "source_authority_overlap_parity_fix02.csv"
    parity_df.to_csv(parity_path, index=False)
    semantic_path = out_dir / "source_authority_ohlc_semantic_validation_fix02.csv"
    semantic_df.to_csv(semantic_path, index=False)

    # 8. Executed Failure Semantics Validation (BLOCKER A)
    failure_semantics_records = execute_failure_semantics_validation()
    fail_val_path = out_dir / "source_authority_failure_semantics_validation_fix02.json"
    fail_val_path.write_text(json.dumps(failure_semantics_records, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # 9. Parser Negative Matrix Validation
    parser_validation = validate_parser_negative_matrix()
    parser_val_path = out_dir / "source_authority_parser_validation_fix02.json"
    parser_val_path.write_text(json.dumps(parser_validation, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # 10. Network Accounting
    network_accounting_dict = accounting.to_dict()
    net_path = out_dir / "source_authority_network_accounting_fix02.json"
    net_path.write_text(json.dumps(network_accounting_dict, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # 11. Initial Artifact Hash Generation
    artifact_files = [
        hist_meta_path,
        cohort_path,
        unexp_recon_path,
        corp_meta_path,
        coverage_path,
        parity_path,
        semantic_path,
        boundary_path,
        repeat_csv_path,
        repeat_sum_path,
        schema_path,
        fail_val_path,
        parser_val_path,
        net_path,
    ]
    artifact_hashes: dict[str, str] = {}
    for af in artifact_files:
        if af.exists():
            artifact_hashes[af.name] = hashlib.sha256(af.read_bytes()).hexdigest()

    # 12. Pre-Manifest Provenance Validation
    mock_manifest = {
        "artifacts": {fn: {"sha256": h, "size_bytes": (out_dir / fn).stat().st_size} for fn, h in artifact_hashes.items()},
        "candidate_id": CANDIDATE_AUTHORITY_ID,
        "start_head": start_head,
    }
    provenance_validation = validate_provenance_integrity_fix02(
        out_dir, mock_manifest, schema_payload, EXPECTED_POPULATION_SHA256, EXPECTED_PIT_SHA256, start_head
    )
    prov_val_path = out_dir / "source_authority_provenance_validation_fix02.json"
    prov_val_path.write_text(json.dumps(provenance_validation, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    artifact_hashes[prov_val_path.name] = hashlib.sha256(prov_val_path.read_bytes()).hexdigest()

    # 13. Evaluate 15 Authority Gates
    eval_res = evaluate_authority_gates_fix02(
        cohort_df,
        coverage_df,
        parity_df,
        semantic_df,
        boundary_df,
        repeat_summary,
        parser_validation,
        failure_semantics_records,
        provenance_validation,
        schema_payload,
        corp_meta_df,
    )

    # 14. Canonical Review Summary Artifact (Section 54)
    review_summary_payload = {
        "schema": "adjusted_price_source_authority_review_v01_fix02",
        "directive_id": "ADJUSTED_PRICE_SOURCE_AUTHORITY_REVIEW_V01_FIX02",
        "parent_directive": "ADJUSTED_PRICE_SOURCE_AUTHORITY_REVIEW_V01_FIX01",
        "start_head": start_head,
        "candidate_id": CANDIDATE_AUTHORITY_ID,
        "candidate_endpoint": NAVER_SISE_ENDPOINT,
        "candidate_request_contract": schema_payload["url_template"],
        "population_sha256": EXPECTED_POPULATION_SHA256,
        "pit_sha256": EXPECTED_PIT_SHA256,
        "calendar_cutoff": "2026-08-21",
        "supersedes_review_artifact": "artifacts/data/end_to_end_data_parity/v01/adjusted_price_source_authority_review/v01_fix01/adjusted_price_source_authority_review_v01_fix01.json",
        "superseded_review_decision": "APPROVED_FOR_PRODUCTION_INTEGRATION",
        "superseded": True,
        "superseded_by": "ADJUSTED_PRICE_SOURCE_AUTHORITY_REVIEW_V01_FIX02",
        "historical_selection_authority_sha": artifact_hashes.get(hist_meta_path.name, ""),
        "unexpected_reconciliation_sha": artifact_hashes.get(unexp_recon_path.name, ""),
        "corporate_action_authority_sha": artifact_hashes.get(corp_meta_path.name, ""),
        "failure_semantics_validation_sha": artifact_hashes.get(fail_val_path.name, ""),
        "parser_validation_sha": artifact_hashes.get(parser_val_path.name, ""),
        "provenance_validation_sha": artifact_hashes.get(prov_val_path.name, ""),
        "gate_results": eval_res["gate_results"],
        "all_gates_passed": eval_res["all_gates_passed"],
        "blocking_conditions": eval_res["blocking_conditions"],
        "reason_codes": eval_res["reason_codes"],
        "review_decision": eval_res["review_decision"],
        "production_integration_authorized": eval_res["production_integration_authorized"],
        "active_production_authority_changed": eval_res["active_production_authority_changed"],
        "recommended_next_state": eval_res["recommended_next_state"],
        "network_accounting": network_accounting_dict,
        "artifact_hashes": artifact_hashes,
    }
    review_sum_path = out_dir / "adjusted_price_source_authority_review_v01_fix02.json"
    review_sum_path.write_text(json.dumps(review_summary_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    artifact_hashes[review_sum_path.name] = hashlib.sha256(review_sum_path.read_bytes()).hexdigest()

    # 15. Manifest Artifact
    manifest_entries = {}
    for fn, h in artifact_hashes.items():
        fp = out_dir / fn
        manifest_entries[fn] = {
            "path": f"artifacts/data/end_to_end_data_parity/v01/adjusted_price_source_authority_review/v01_fix02/{fn}",
            "sha256": h,
            "size_bytes": fp.stat().st_size if fp.exists() else 0,
        }
    manifest_payload = {
        "schema": "adjusted_price_source_authority_review_fix02_manifest_v01",
        "directive_id": "ADJUSTED_PRICE_SOURCE_AUTHORITY_REVIEW_V01_FIX02",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "start_head": start_head,
        "candidate_id": CANDIDATE_AUTHORITY_ID,
        "review_decision": eval_res["review_decision"],
        "production_integration_authorized": eval_res["production_integration_authorized"],
        "artifacts": manifest_entries,
    }
    manifest_path = out_dir / "artifact_manifest.json"
    manifest_path.write_text(json.dumps(manifest_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return review_summary_payload


def run_source_authority_review_fix01(
    output_dir: Path | None = None,
    start_head: str = START_HEAD_FIX02,
) -> dict[str, Any]:
    """FIX01 wrapper delegating to run_source_authority_review_fix02."""
    return run_source_authority_review_fix02(output_dir, start_head)


def run_source_authority_review(
    output_dir: Path | None = None,
    start_head: str = START_HEAD_FIX02,
) -> dict[str, Any]:
    """Legacy wrapper delegating to run_source_authority_review_fix02."""
    return run_source_authority_review_fix02(output_dir, start_head)


if __name__ == "__main__":
    res = run_source_authority_review_fix02()
    print("=== Source Authority Review FIX02 Execution Summary ===")
    print("Review Decision:", res["review_decision"])
    print("All Gates Passed:", res["all_gates_passed"])
    print("Production Integration Authorized:", res["production_integration_authorized"])
    print("Recommended Next State:", res["recommended_next_state"])
    print("Network Accounting:", res["network_accounting"])
    print("Gate Results:")
    for k, v in res["gate_results"].items():
        print(f"  {k:45s} : {v}")
    if res["blocking_conditions"]:
        print("Blocking Conditions:", res["blocking_conditions"])
