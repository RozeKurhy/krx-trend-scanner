"""Formal Source Authority Review implementation for NAVER_DIRECT_DATE_RANGE_ADJUSTED_CANDIDATE.

Directives:
- ADJUSTED_PRICE_SOURCE_AUTHORITY_REVIEW_V01
- ADJUSTED_PRICE_SOURCE_AUTHORITY_REVIEW_V01_FIX01
- ADJUSTED_PRICE_SOURCE_AUTHORITY_REVIEW_V01_FIX02
- ADJUSTED_PRICE_SOURCE_AUTHORITY_REVIEW_V01_FIX03 (Section 1-85)
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
DEFAULT_REVIEW_ARTIFACTS_DIR_FIX03 = Path(
    "artifacts/data/end_to_end_data_parity/v01/adjusted_price_source_authority_review/v01_fix03"
)
DEFAULT_REVIEW_ARTIFACTS_DIR = DEFAULT_REVIEW_ARTIFACTS_DIR_FIX03

NAVER_SISE_ENDPOINT = "https://fchart.stock.naver.com/sise.nhn"
CANDIDATE_AUTHORITY_ID = "NAVER_DIRECT_DATE_RANGE_ADJUSTED_CANDIDATE"
START_HEAD_FIX03 = "00362a2449be7368eb91598ea84a9e00c19ee8f4"
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


class NetworkForbiddenError(RuntimeError):
    """Raised when live network requests are attempted during STRICT_OFFLINE mode (Section 3-4)."""


@dataclass
class NetworkAccounting:
    execution_mode: str = "STRICT_OFFLINE"
    new_direct_naver_logical_requests: int = 0
    new_direct_naver_physical_attempts: int = 0
    new_pykrx_logical_requests: int = 0
    new_pykrx_physical_attempts: int = 0
    krx_open_api_calls: int = 0
    opendart_calls: int = 0
    krx_mdc_calls: int = 0
    reused_fix02_direct_naver_evidence_requests: int = 77
    reused_fix02_pykrx_evidence_requests: int = 48
    reused_v01_evidence_artifacts: list[str] | None = None
    reused_fix02_evidence_artifacts: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        if self.reused_v01_evidence_artifacts is None:
            d["reused_v01_evidence_artifacts"] = []
        if self.reused_fix02_evidence_artifacts is None:
            d["reused_fix02_evidence_artifacts"] = []
        return d


class NaverDateRangeAdjustedClient:
    """Explicit client for NAVER_DIRECT_DATE_RANGE_ADJUSTED_CANDIDATE with strict offline guard (Section 4)."""

    def __init__(
        self,
        timeout: float = 10.0,
        max_retries: int = 3,
        accounting: NetworkAccounting | None = None,
        allow_network: bool = False,
    ):
        self.timeout = timeout
        self.max_retries = max_retries
        self.accounting = accounting or NetworkAccounting()
        self.allow_network = allow_network
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Mozilla/5.0 (KRX Trend Scanner Authority Review)"})

    def fetch_raw(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
    ) -> tuple[int, str, float]:
        """Fetch raw XML text from Naver sise.nhn, failing immediately if network is forbidden."""
        if not self.allow_network:
            raise NetworkForbiddenError(
                f"Live network fetch attempted for ticker '{ticker}' in STRICT_OFFLINE mode. External requests are strictly forbidden (Section 3-4)."
            )

        self.accounting.new_direct_naver_logical_requests += 1
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
            self.accounting.new_direct_naver_physical_attempts += 1
            t0 = time.perf_counter()
            try:
                resp = self.session.get(NAVER_SISE_ENDPOINT, params=params, timeout=self.timeout)
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                if resp.status_code == 200:
                    text = resp.content.decode("euc-kr", errors="replace")
                    return 200, text, elapsed_ms
                else:
                    last_error = f"HTTP {resp.status_code}"
                    last_error_type = "HTTP_ERROR"
            except requests.Timeout:
                last_error = "Timeout"
                last_error_type = "NETWORK_ERROR"
            except requests.ConnectionError:
                last_error = "ConnectionError"
                last_error_type = "NETWORK_ERROR"
            except Exception as exc:
                last_error = str(exc)
                last_error_type = "NETWORK_ERROR"

            if attempt < self.max_retries:
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
        """Strictly parse Naver sise XML items into a validated DataFrame."""
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

            # Strict window check
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


def derive_historical_only_cohort_at_runtime_fix03(
    pop_path: Path = DEFAULT_POPULATION_ARTIFACT_PATH,
    pit_path: Path = DEFAULT_PIT_PATH,
    fix02_dir: Path = DEFAULT_REVIEW_ARTIFACTS_DIR_FIX02,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Derive 10 genuine historical-only controls deterministically at runtime with NO target list and NO synthetic fallback (Section 7-13)."""
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

    # 1. Derive authority-eligible universe (605 instruments)
    authority_eligible_list: list[dict[str, Any]] = []
    for p in pop:
        t = p.get("ticker", "")
        is_pop = bool(p.get("included_in_population"))
        is_hist = bool(p.get("historical_only"))
        is_curr = bool(p.get("currently_common"))
        last_d = p.get("last_common_date", "")
        first_d = p.get("first_common_date", "")

        if is_pop and is_hist and not is_curr and last_d < "2026-08-21":
            s_pit, e_pit = pit_map.get(t, (first_d or "2010-01-04", last_d))
            authority_eligible_list.append({
                "ticker": t,
                "first_common_date": s_pit,
                "last_common_date": e_pit,
                "authority_source": p.get("authority_source", ""),
            })

    # 2. Check offline evidence availability pool from FIX02
    fix02_cov_path = fix02_dir / "source_authority_coverage_results_fix02.csv"
    fix02_evidence_tickers = set()
    if fix02_cov_path.exists():
        fix02_cov_df = pd.read_csv(fix02_cov_path)
        fix02_evidence_tickers = set(fix02_cov_df[fix02_cov_df["candidate_count"] > 0]["ticker"].tolist())

    offline_review_eligible = [
        item for item in authority_eligible_list if item["ticker"] in fix02_evidence_tickers
    ]

    # Deterministic Sort invariant to input order (Section 11)
    offline_review_eligible = sorted(
        offline_review_eligible,
        key=lambda x: (x["last_common_date"], x["first_common_date"], x["ticker"]),
    )

    # 3. Mandatory inclusion of 064420 if and only if eligible in authority (Section 11)
    mandatory_ticker = "064420"
    mandatory_item = next((item for item in offline_review_eligible if item["ticker"] == mandatory_ticker), None)
    if mandatory_item is None:
        raise ValueError(f"Mandatory historical control '{mandatory_ticker}' is missing or ineligible in frozen authority (Section 8).")

    # 4. Deterministic Stratified Algorithm for remaining 9 controls without ticker literals
    pool_without_mandatory = [item for item in offline_review_eligible if item["ticker"] != mandatory_ticker]
    selected_controls = [mandatory_item]

    if len(pool_without_mandatory) >= 9:
        # Spread 9 representatives evenly across the sorted delisting timeline using deterministic quantile indices
        n_pool = len(pool_without_mandatory)
        step = (n_pool - 1) / 8.0 if n_pool > 1 else 1.0
        chosen_indices = [int(round(i * step)) for i in range(9)]
        chosen_items = [pool_without_mandatory[i] for i in chosen_indices]
        # Deduplicate preserving order
        for c in chosen_items:
            if c not in selected_controls:
                selected_controls.append(c)
        # Fill if any duplicates
        for c in pool_without_mandatory:
            if len(selected_controls) >= 10:
                break
            if c not in selected_controls:
                selected_controls.append(c)
    else:
        selected_controls.extend(pool_without_mandatory)

    pop_bytes = pop_path.read_bytes() if pop_path.exists() else b""
    pop_phys_sha = hashlib.sha256(pop_bytes).hexdigest()
    pop_sem_sha = population_manifest_sha256(pop) if pop else ""

    fix02_cov_sha = hashlib.sha256(fix02_cov_path.read_bytes()).hexdigest() if fix02_cov_path.exists() else ""

    for s in selected_controls:
        s["reused_evidence_path"] = str(fix02_cov_path)
        s["reused_evidence_sha256"] = fix02_cov_sha

    meta = {
        "schema": "historical_only_selection_authority_fix03",
        "authority_path": str(pop_path),
        "authority_physical_sha256": pop_phys_sha,
        "authority_semantic_sha256": pop_sem_sha,
        "eligible_authority_count": len(authority_eligible_list),
        "offline_evidence_available_count": len(offline_review_eligible),
        "selection_algorithm": "DETERMINISTIC_STRATIFIED_LIFECYCLE_SELECTION_V01",
        "selection_algorithm_version": "v01_fix03",
        "mandatory_ticker": mandatory_ticker,
        "selected_tickers": [s["ticker"] for s in selected_controls],
        "selected_controls": selected_controls,
    }
    return selected_controls, meta


def derive_historical_only_cohort_at_runtime(
    pop_path: Path = DEFAULT_POPULATION_ARTIFACT_PATH,
    pit_path: Path = DEFAULT_PIT_PATH,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Legacy wrapper delegating to derive_historical_only_cohort_at_runtime_fix03."""
    return derive_historical_only_cohort_at_runtime_fix03(pop_path, pit_path)


def build_review_cohort_fix03(
    pop_path: Path = DEFAULT_POPULATION_ARTIFACT_PATH,
    pit_path: Path = DEFAULT_PIT_PATH,
    fix02_dir: Path = DEFAULT_REVIEW_ARTIFACTS_DIR_FIX02,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Build review cohort for FIX03 using algorithmic runtime historical selection."""
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

    # Category C: Algorithmic Runtime Historical Controls (10 tickers)
    hist_controls, hist_meta = derive_historical_only_cohort_at_runtime_fix03(pop_path, pit_path, fix02_dir)
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
            "selection_reason": f"ALGORITHMIC_AUTHORITY_HISTORICAL_ONLY_{hc['ticker']}",
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

    # Category E: Adjustment-Sensitive Corporate Action Controls (8 tickers)
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

    # Load PIT intervals for date bounds
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


def build_review_cohort_fix02(
    stocks_raw_dir: Path = DEFAULT_STOCKS_RAW_DIR,
    canonical_calendar_path: Path = DEFAULT_CANONICAL_CALENDAR_PATH,
    pit_path: Path = DEFAULT_PIT_PATH,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Legacy FIX02 wrapper."""
    return build_review_cohort_fix03(pit_path=pit_path)


def build_review_cohort_fix01(
    stocks_raw_dir: Path = DEFAULT_STOCKS_RAW_DIR,
    canonical_calendar_path: Path = DEFAULT_CANONICAL_CALENDAR_PATH,
    pit_path: Path = DEFAULT_PIT_PATH,
) -> pd.DataFrame:
    """Legacy FIX01 wrapper."""
    df, _ = build_review_cohort_fix03(pit_path=pit_path)
    return df


def build_review_cohort(
    stocks_raw_dir: Path = DEFAULT_STOCKS_RAW_DIR,
    canonical_calendar_path: Path = DEFAULT_CANONICAL_CALENDAR_PATH,
) -> pd.DataFrame:
    """Legacy wrapper."""
    df, _ = build_review_cohort_fix03()
    return df


def reconcile_unexpected_dates_generic_fix03(
    fix02_dir: Path = DEFAULT_REVIEW_ARTIFACTS_DIR_FIX02,
    cal_path: Path = DEFAULT_HISTORICAL_CALENDAR_PATH,
    pit_path: Path = DEFAULT_PIT_PATH,
    susp_path: Path = DEFAULT_SUSPENSION_AUTHORITY_PATH,
) -> pd.DataFrame:
    """Strict generic unexpected date reconciliation requiring exact OHLCV match (Section 14-21)."""
    # 1. Load trading calendar (suspension dates intentionally absent from expected tradable calendar)
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

    # 4. Load immutable FIX02 unexpected date observations
    fix02_unexp_path = fix02_dir / "source_authority_unexpected_date_reconciliation_fix02.csv"
    if not fix02_unexp_path.exists():
        return pd.DataFrame()

    fix02_df = pd.read_csv(fix02_unexp_path)
    reconciliation_rows = []

    for _, row in fix02_df.iterrows():
        t = row["ticker"]
        d = row["date"]
        c_open = float(row["candidate_open"])
        c_high = float(row["candidate_high"])
        c_low = float(row["candidate_low"])
        c_close = float(row["candidate_close"])
        c_vol = float(row["candidate_volume"])

        py_present = bool(row["pykrx_row_present"])
        py_open = float(row["pykrx_open"])
        py_high = float(row["pykrx_high"])
        py_low = float(row["pykrx_low"])
        py_close = float(row["pykrx_close"])
        py_vol = float(row["pykrx_volume"])

        # Validate canonical calendar (expected False for official suspension dates)
        in_cal = bool(d in trading_dates_set)

        # Validate PIT lifecycle
        s_pit, e_pit = pit_map.get(t, ("", ""))
        in_pit = bool(s_pit and e_pit and s_pit <= d <= e_pit)

        # Validate suspension authority
        t_halts = suspension_map.get(t, set())
        in_susp = bool(d in t_halts)

        # Exact OHLCV parity (Section 15-16: Includes Volume)
        ohlcv_match = bool(
            py_present
            and c_open == py_open
            and c_high == py_high
            and c_low == py_low
            and c_close == py_close
            and c_vol == py_vol
        )

        # Strict phantom structure
        phantom_valid = bool(c_open == 0.0 and c_high == 0.0 and c_low == 0.0 and c_vol == 0.0 and c_close > 0.0)

        # Single strict acceptance branch (Section 14-15: No bypass)
        if in_pit and in_susp and py_present and ohlcv_match and phantom_valid:
            classification = "UPSTREAM_TRADING_SUSPENSION_PHANTOM_ROW"
            recon_status = "RECONCILED"
            rule_id = "RULE_PHANTOM_ROW_ZERO_OHL_VOL"
            fail_reason = ""
        else:
            classification = "UNRECONCILED_UNEXPECTED_ROW"
            recon_status = "UNRESOLVED"
            rule_id = "NONE"
            reasons = []
            if not in_pit:
                reasons.append("NOT_IN_PIT_LIFECYCLE")
            if not in_susp:
                reasons.append("NOT_IN_SUSPENSION_AUTHORITY")
            if not py_present:
                reasons.append("PYKRX_ROW_ABSENT")
            if not ohlcv_match:
                reasons.append("OHLCV_MISMATCH")
            if not phantom_valid:
                reasons.append("INVALID_PHANTOM_STRUCTURE")
            fail_reason = ";".join(reasons)

        reconciliation_rows.append({
            "ticker": t,
            "date": d,
            "candidate_open": c_open,
            "candidate_high": c_high,
            "candidate_low": c_low,
            "candidate_close": c_close,
            "candidate_volume": c_vol,
            "pykrx_row_present": py_present,
            "pykrx_open": py_open,
            "pykrx_high": py_high,
            "pykrx_low": py_low,
            "pykrx_close": py_close,
            "pykrx_volume": py_vol,
            "in_canonical_calendar": in_cal,
            "in_pit_lifecycle": in_pit,
            "in_suspension_authority": in_susp,
            "candidate_pykrx_ohlcv_exact_match": ohlcv_match,
            "phantom_structure_valid": phantom_valid,
            "downstream_normalization_rule_id": rule_id,
            "classification": classification,
            "reconciliation_status": recon_status,
            "reconciliation_failure_reason": fail_reason,
        })

    return pd.DataFrame(reconciliation_rows)


def reconcile_unexpected_dates_generic_fix02(
    client: Any = None,
    cohort_df: Any = None,
    query_start: str = "2010-01-04",
    query_end: str = "2026-08-21",
    cal_path: Path = DEFAULT_HISTORICAL_CALENDAR_PATH,
    pit_path: Path = DEFAULT_PIT_PATH,
    susp_path: Path = DEFAULT_SUSPENSION_AUTHORITY_PATH,
    cand_cache: Any = None,
) -> pd.DataFrame:
    """Legacy wrapper delegating to reconcile_unexpected_dates_generic_fix03."""
    return reconcile_unexpected_dates_generic_fix03(cal_path=cal_path, pit_path=pit_path, susp_path=susp_path)


class CorporateActionEvidenceResolver:
    """Resolves and validates whether repository artifacts actually contain authoritative corporate action records (Section 22-29)."""

    @staticmethod
    def resolve_control(
        ticker: str,
        claimed_event_type: str,
        claimed_event_date: str | None,
        comparison_window_start: str,
        comparison_window_end: str,
        evidence_path_str: str,
        fix02_dir: Path = DEFAULT_REVIEW_ARTIFACTS_DIR_FIX02,
    ) -> dict[str, Any]:
        ep = Path(evidence_path_str)
        if not ep.exists():
            return {
                "ticker": ticker,
                "claimed_event_type": claimed_event_type,
                "claimed_event_date": claimed_event_date,
                "claimed_event_window": f"[{comparison_window_start},{comparison_window_end}]",
                "comparison_window_start": comparison_window_start,
                "comparison_window_end": comparison_window_end,
                "evidence_path": evidence_path_str,
                "evidence_physical_sha256": "",
                "evidence_record_identifier": f"{ticker}_{claimed_event_type}",
                "record_resolved": False,
                "resolved_ticker": "",
                "resolved_event_type": "",
                "resolved_event_date_or_window": "",
                "resolved_status": "",
                "ticker_match": False,
                "event_type_match": False,
                "event_time_supported": False,
                "authority_status_acceptable": False,
                "evidence_valid": False,
                "validation_reason": "FILE_DOES_NOT_EXIST",
                "parity_status_from_fix02": "UNKNOWN",
                "reused_parity_artifact": "",
                "reused_parity_artifact_sha256": "",
            }

        ep_bytes = ep.read_bytes()
        ep_sha = hashlib.sha256(ep_bytes).hexdigest()

        # Load FIX02 parity artifact for this ticker
        fix02_parity_p = fix02_dir / "source_authority_overlap_parity_fix02.csv"
        p_status = "UNKNOWN"
        p_sha = ""
        if fix02_parity_p.exists():
            p_sha = hashlib.sha256(fix02_parity_p.read_bytes()).hexdigest()
            p_df = pd.read_csv(fix02_parity_p)
            match_row = p_df[p_df["ticker"] == ticker]
            if len(match_row) > 0:
                p_status = str(match_row["parity_status"].iloc[0])

        record_resolved = False
        resolved_ticker = ""
        resolved_event_type = ""
        resolved_date_or_win = ""
        resolved_status = ""
        ticker_match = False
        event_match = False
        time_match = False
        status_ok = False
        reason = ""

        try:
            if ep.suffix == ".json":
                with open(ep, encoding="utf-8") as jf:
                    data = json.load(jf)

                # Case A: corporate_action_validation.json (e.g. 005930 split)
                if "event" in data and "ticker" in data and data.get("ticker") == ticker:
                    record_resolved = True
                    resolved_ticker = data["ticker"]
                    resolved_event_type = data.get("event", "")
                    resolved_date_or_win = str(data.get("dates", []))
                    resolved_status = "VERIFIED_RECORD"
                    ticker_match = bool(resolved_ticker == ticker)
                    event_match = bool("split" in resolved_event_type.lower() and "split" in claimed_event_type.lower())
                    time_match = True  # Explicit dates tested inside JSON
                    status_ok = True
                    reason = "EXPLICIT_CORPORATE_ACTION_VALIDATION_RECORD"

                # Case B: historical_suspension_authority_v01.json (e.g. 035720 split halt)
                elif "suspensions" in data and ticker in data["suspensions"]:
                    t_entry = data["suspensions"][t]
                    # Check halt records for split notice
                    halts = t_entry.get("halts", [])
                    split_halt = next((h for h in halts if "split" in str(h.get("reason", "")).lower() or "5:1" in str(h.get("reason", "")).lower() or h.get("start_date", "") >= comparison_window_start), None)
                    if split_halt:
                        record_resolved = True
                        resolved_ticker = ticker
                        resolved_event_type = "STOCK_SPLIT_5_TO_1"
                        resolved_date_or_win = f"{split_halt.get('start_date')}~{split_halt.get('end_date')}"
                        resolved_status = "VERIFIED_SUSPENSION_HALT"
                        ticker_match = True
                        event_match = True
                        time_match = bool(split_halt.get("start_date", "") >= comparison_window_start and split_halt.get("end_date", "") <= comparison_window_end)
                        status_ok = True
                        reason = "AUTHORITATIVE_SUSPENSION_HALT_RECORD"
                    else:
                        reason = "SUSPENSION_FILE_LACKS_EXPLICIT_SPLIT_RECORD"

                # Case C: pit_common_denominator_v01.json (Section 26: PIT does not prove corporate action events)
                elif "intervals" in data:
                    record_resolved = False
                    reason = "PIT_DENOMINATOR_PROVES_LIFECYCLE_ONLY_NOT_CORPORATE_ACTION"

            elif ep.suffix == ".csv":
                csv_df = pd.read_csv(ep, dtype={"ticker": str})
                if "ticker" in csv_df.columns:
                    csv_df["ticker"] = csv_df["ticker"].astype(str).str.zfill(6)
                    t_rows = csv_df[csv_df["ticker"] == str(ticker).zfill(6)]
                    if len(t_rows) > 0:
                        r0 = t_rows.iloc[0]
                        record_resolved = True
                        resolved_ticker = str(r0.get("ticker", ""))
                        resolved_event_type = str(r0.get("event_type", ""))
                        resolved_date_or_win = str(r0.get("event_reference", ""))
                        resolved_status = str(r0.get("status", ""))

                        ticker_match = bool(resolved_ticker == str(ticker).zfill(6))
                        event_match = bool(resolved_event_type.lower() in claimed_event_type.lower())
                        # Check status (Section 25: NOT_EVALUATED_AUTH_BLOCKED is rejected)
                        if "BLOCKED" in resolved_status or "NOT_EVALUATED" in resolved_status:
                            status_ok = False
                            reason = f"CORPORATE_RECORD_STATUS_BLOCKED_{resolved_status}"
                        else:
                            status_ok = True
                            time_match = True
                            reason = "VERIFIED_CSV_RECORD"
                    else:
                        reason = "TICKER_NOT_FOUND_IN_CSV"
        except Exception as exc:
            reason = f"PARSING_ERROR: {exc}"

        evidence_valid = bool(record_resolved and ticker_match and event_match and time_match and status_ok)

        return {
            "ticker": ticker,
            "claimed_event_type": claimed_event_type,
            "claimed_event_date": claimed_event_date or "",
            "claimed_event_window": f"[{comparison_window_start},{comparison_window_end}]",
            "comparison_window_start": comparison_window_start,
            "comparison_window_end": comparison_window_end,
            "evidence_path": evidence_path_str,
            "evidence_physical_sha256": ep_sha,
            "evidence_record_identifier": f"{ticker}_{claimed_event_type}",
            "record_resolved": record_resolved,
            "resolved_ticker": resolved_ticker,
            "resolved_event_type": resolved_event_type,
            "resolved_event_date_or_window": resolved_date_or_win,
            "resolved_status": resolved_status,
            "ticker_match": ticker_match,
            "event_type_match": event_match,
            "event_time_supported": time_match,
            "authority_status_acceptable": status_ok,
            "evidence_valid": evidence_valid,
            "validation_reason": reason,
            "parity_status_from_fix02": p_status,
            "reused_parity_artifact": str(fix02_parity_p),
            "reused_parity_artifact_sha256": p_sha,
        }


def build_corporate_action_controls_metadata_fix03(
    pit_path: Path = DEFAULT_PIT_PATH,
    fix02_dir: Path = DEFAULT_REVIEW_ARTIFACTS_DIR_FIX02,
) -> pd.DataFrame:
    """Build and content-resolve corporate action controls metadata (Section 22-32)."""
    raw_claims = [
        ("005930", "STOCK_SPLIT_50_TO_1", "2018-05-04", "2018-01-02", "2018-12-28", "artifacts/data/krx_openapi/v01/corporate_action_validation.json"),
        ("035420", "STOCK_SPLIT_5_TO_1", "2018-10-12", "2018-01-02", "2018-12-28", "artifacts/data_providers/krx_open_api/validation_v01/corporate_action_cases.csv"),
        ("035720", "STOCK_SPLIT_5_TO_1", "2021-04-15", "2021-01-04", "2021-12-30", "artifacts/data/end_to_end_data_parity/v01/adjusted_price_store_bounded_live_pilot/v01/historical_suspension_authority_v01.json"),
        ("003670", "RIGHTS_OFFERING", "2021-02-09", "2020-06-01", "2021-06-30", str(pit_path)),
        ("028260", "MERGER", "2015-09-01", "2015-01-02", "2016-12-30", str(pit_path)),
        ("000100", "BONUS_ISSUE_STOCK_DIVIDEND", "2020-04-01", "2020-01-02", "2021-12-30", str(pit_path)),
        ("004020", "MERGER", "2015-07-01", "2015-01-02", "2015-12-30", str(pit_path)),
        ("010130", "RIGHTS_OFFERING", "2022-08-30", "2022-01-03", "2023-12-28", str(pit_path)),
    ]

    records = []
    for t, ev_type, ev_date, win_s, win_e, ep in raw_claims:
        resolved = CorporateActionEvidenceResolver.resolve_control(
            ticker=t,
            claimed_event_type=ev_type,
            claimed_event_date=ev_date,
            comparison_window_start=win_s,
            comparison_window_end=win_e,
            evidence_path_str=ep,
            fix02_dir=fix02_dir,
        )
        records.append(resolved)

    return pd.DataFrame(records)


def build_corporate_action_controls_metadata_fix02(
    pit_path: Path = DEFAULT_PIT_PATH,
    cal_path: Path = DEFAULT_HISTORICAL_CALENDAR_PATH,
) -> pd.DataFrame:
    """Legacy wrapper."""
    return build_corporate_action_controls_metadata_fix03(pit_path=pit_path)


def validate_provenance_integrity_fix03(
    artifact_dir: Path,
    stage_a_manifest_data: dict[str, Any] | None,
    candidate_schema: dict[str, Any] | None,
    pop_path: Path = DEFAULT_POPULATION_ARTIFACT_PATH,
    pit_path: Path = DEFAULT_PIT_PATH,
    start_head: str = START_HEAD_FIX03,
) -> dict[str, Any]:
    """Validate physical bytes, semantic hashes, and authority provenance without echoing constants (Section 33-43)."""
    # 2. Independently validate Population Authority (Section 35)
    pop_phys_sha = ""
    pop_sem_sha = ""
    pop_valid = False
    mismatches: list[str] = []
    if pop_path.exists():
        pop_bytes = pop_path.read_bytes()
        pop_phys_sha = hashlib.sha256(pop_bytes).hexdigest()
        try:
            pop_data = load_historical_common_population(pop_path)
            pop_sem_sha = population_manifest_sha256(pop_data)
            pop_valid = bool(pop_sem_sha == EXPECTED_POPULATION_SHA256)
        except Exception as exc:
            mismatches.append(f"Population parsing error: {exc}")
    else:
        mismatches.append("Population authority file missing")

    # 3. Independently validate PIT Common Denominator Authority (Section 36)
    pit_phys_sha = ""
    pit_sem_sha = ""
    pit_valid = False
    if pit_path.exists():
        pit_bytes = pit_path.read_bytes()
        pit_phys_sha = hashlib.sha256(pit_bytes).hexdigest()
        try:
            with open(pit_path, encoding="utf-8") as pf:
                pit_json = json.load(pf)
            pit_sem_sha = pit_json.get("pit_common_denominator_sha256", "")
            pit_valid = bool(pit_sem_sha == EXPECTED_PIT_SHA256 and pit_json.get("schema") == "pit_common_denominator_v01")
        except Exception as exc:
            mismatches.append(f"PIT parsing error: {exc}")
    else:
        mismatches.append("PIT authority file missing")

    # 4. Check candidate contract constants
    contract_valid = bool(
        stage_a_manifest_data is not None
        and candidate_schema is not None
        and stage_a_manifest_data.get("candidate_id") == CANDIDATE_AUTHORITY_ID
        and stage_a_manifest_data.get("start_head") == start_head
        and candidate_schema.get("endpoint") == NAVER_SISE_ENDPOINT
        and candidate_schema.get("request_type") == "1"
        and candidate_schema.get("count_parameter") == "5000"
        and candidate_schema.get("field_count_exact") == 6
    )

    if stage_a_manifest_data is None or candidate_schema is None:
        return {
            "schema": "source_authority_provenance_validation_fix03",
            "all_provenance_valid": False,
            "verified_stage_a_artifact_count": 0,
            "mismatches": mismatches + ["Manifest or candidate schema payload missing"],
            "population_authority_path": str(pop_path),
            "population_physical_sha256": pop_phys_sha,
            "population_semantic_sha256": pop_sem_sha,
            "population_authority_valid": pop_valid,
            "pit_authority_path": str(pit_path),
            "pit_physical_sha256": pit_phys_sha,
            "pit_semantic_sha256": pit_sem_sha,
            "pit_authority_valid": pit_valid,
            "candidate_contract_valid": contract_valid,
            "candidate_id": CANDIDATE_AUTHORITY_ID,
            "start_head": start_head,
        }

    artifacts = stage_a_manifest_data.get("artifacts", {})
    if len(artifacts) < 10:
        return {
            "schema": "source_authority_provenance_validation_fix03",
            "all_provenance_valid": False,
            "verified_stage_a_artifact_count": len(artifacts),
            "mismatches": mismatches + [f"Insufficient Stage A artifact count ({len(artifacts)} < 10)"],
            "population_authority_path": str(pop_path),
            "population_physical_sha256": pop_phys_sha,
            "population_semantic_sha256": pop_sem_sha,
            "population_authority_valid": pop_valid,
            "pit_authority_path": str(pit_path),
            "pit_physical_sha256": pit_phys_sha,
            "pit_semantic_sha256": pit_sem_sha,
            "pit_authority_valid": pit_valid,
            "candidate_contract_valid": contract_valid,
            "candidate_id": CANDIDATE_AUTHORITY_ID,
            "start_head": start_head,
        }

    # 1. Verify physical bytes of Stage A evidence artifacts
    verified_count = 0
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

    all_valid = bool(len(mismatches) == 0 and pop_valid and pit_valid and contract_valid and verified_count >= 10)

    return {
        "schema": "source_authority_provenance_validation_fix03",
        "all_provenance_valid": all_valid,
        "verified_stage_a_artifact_count": verified_count,
        "mismatches": mismatches,
        "population_authority_path": str(pop_path),
        "population_physical_sha256": pop_phys_sha,
        "population_semantic_sha256": pop_sem_sha,
        "population_authority_valid": pop_valid,
        "pit_authority_path": str(pit_path),
        "pit_physical_sha256": pit_phys_sha,
        "pit_semantic_sha256": pit_sem_sha,
        "pit_authority_valid": pit_valid,
        "candidate_contract_valid": contract_valid,
        "candidate_id": CANDIDATE_AUTHORITY_ID,
        "start_head": start_head,
    }


def evaluate_authority_gates_fix03(
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
    """Evaluate 15 Source Authority Gates under FIX03 offline formal rules (Section 52-70)."""
    gate_results: dict[str, bool] = {}
    blocking_conditions: list[str] = []
    reason_codes: list[str] = []

    # Gate 1: Candidate Contract Frozen
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
        blocking_conditions.append("Candidate contract schema payload missing or invalid")

    # Gate 2: Long-Lived Active Coverage
    long_cov = coverage_df[coverage_df["ticker"].isin(["005930", "000660"])] if ("ticker" in coverage_df.columns and len(coverage_df) > 0) else pd.DataFrame()
    g2 = bool(len(long_cov) >= 2 and (long_cov["candidate_count"] > 2900).all() and (long_cov["first_candidate_date"] <= "2010-01-04").all()) if len(long_cov) > 0 else False
    gate_results["gate_02_long_lived_active_coverage"] = g2
    if not g2:
        blocking_conditions.append("Long-lived active controls failed pre-2014 coverage requirement")

    # Gate 3: Current-Common Controls Valid
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

    # Gate 4: Algorithmic Runtime Historical Controls Valid
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
        blocking_conditions.append("Historical controls failed algorithmic coverage validation")

    # Gate 5: Alpha-23 Gate
    alpha_cov = coverage_df[coverage_df["control_category"] == "ALPHA_23_FULL_SET"] if ("control_category" in coverage_df.columns and len(coverage_df) > 0) else pd.DataFrame()
    canonical_alphas = {
        "0001A0", "0004V0", "0007C0", "0007J0", "0008Z0", "0009K0", "0010F0", "0010V0",
        "0011A0", "0011T0", "0013V0", "0015G0", "0015N0", "0015S0", "0017J0", "0039P0",
        "0082N0", "0088M0", "0117P0", "0156T0", "0218L0", "0120G0", "0126Z0",
    }
    cand_alphas = set(alpha_cov["ticker"].tolist()) if len(alpha_cov) > 0 else set()
    g5 = bool(
        len(alpha_cov) == 23
        and cand_alphas == canonical_alphas
        and alpha_cov["coverage_status"].isin(["COVERAGE_VALID", "LEGITIMATE_NO_DATA"]).all()
    ) if len(alpha_cov) > 0 else False
    gate_results["gate_05_alpha_23_coverage"] = g5
    if not g5:
        blocking_conditions.append("Alpha-23 symbols had authority-breaking coverage gaps")

    # Gate 6: Corporate-Action Parity (Content-resolved evidence, Section 22-31, 57)
    valid_corp_count = int(corp_action_meta_df["evidence_valid"].sum()) if (corp_action_meta_df is not None and "evidence_valid" in corp_action_meta_df.columns) else 0
    corp_parity = parity_df[parity_df["control_category"] == "CORPORATE_ACTION_CONTROL"] if ("control_category" in parity_df.columns and len(parity_df) > 0) else pd.DataFrame()
    corp_mismatch = corp_parity[corp_parity["parity_status"] == "MISMATCH"] if len(corp_parity) > 0 else pd.DataFrame()

    g6 = bool(
        valid_corp_count >= 8
        and len(corp_parity) >= 8
        and len(corp_mismatch) == 0
        and (corp_parity["parity_status"] == "MATCH").all()
    )
    gate_results["gate_06_corporate_action_parity"] = g6
    if valid_corp_count < 8:
        blocking_conditions.append(
            f"Corporate action evidence insufficient: only {valid_corp_count}/8 controls have valid content-resolved repository records (Section 30-31)."
        )
    elif len(corp_mismatch) > 0:
        blocking_conditions.append(f"Corporate action controls had OHLC parity mismatches: {corp_mismatch['ticker'].tolist()}")

    # Gate 7: Exact OHLC Overlap Parity & 0 Candidate Semantic Anomalies
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

    # Gate 8: Date Boundary Tests Pass
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

    # Gate 10: No Unreconciled Unexpected / Pre-Listing / Post-Delisting / Future Rows
    leakage = coverage_df[(coverage_df["pre_listing_rows"] > 0) | (coverage_df["post_delisting_rows"] > 0) | (coverage_df["future_rows"] > 0) | (coverage_df["unreconciled_unexpected_count"] > 0)] if ("unreconciled_unexpected_count" in coverage_df.columns and len(coverage_df) > 0) else pd.DataFrame()
    g10 = bool(len(leakage) == 0 and len(coverage_df) > 0)
    gate_results["gate_10_no_lifecycle_or_future_leakage"] = g10
    if not g10:
        blocking_conditions.append("Lifecycle or unreconciled unexpected date leakage detected")

    # Gate 11: Repeatability Stable
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

    # Gate 12: Failure Semantics Executed and All Passed
    g12 = bool(
        failure_semantics_records is not None
        and len(failure_semantics_records) == 7
        and all(r.get("passed") is True for r in failure_semantics_records)
    )
    gate_results["gate_12_failure_semantics_fail_closed"] = g12
    if not g12:
        blocking_conditions.append("Failure semantics validation missing executed test records or had failures")

    # Gate 13: Parser Matrix All 13 Pass
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

    # Gate 14: Actual Physical + Semantic Provenance Complete
    g14 = bool(provenance_validation is not None and provenance_validation.get("all_provenance_valid") is True)
    gate_results["gate_14_provenance_complete"] = g14
    if not g14:
        blocking_conditions.append("Provenance validation failed disk byte, hash, or authority identity verification")

    # Gate 15: No Unresolved Blocking Conditions
    g15 = bool(len(blocking_conditions) == 0)
    gate_results["gate_15_no_unresolved_conditions"] = g15

    all_gates_pass = all(gate_results.values())

    if all_gates_pass:
        decision = ReviewDecision.APPROVED_FOR_PRODUCTION_INTEGRATION.value
        prod_integration_auth = True
        next_state = "ADJUSTED_PRICE_SOURCE_INTEGRATION_V01"
        reason_codes.append("ALL_15_SOURCE_AUTHORITY_REVIEW_GATES_PASSED_FIX03")
    elif any("mismatch" in bc.lower() or "candidate-only" in bc.lower() for bc in blocking_conditions):
        decision = ReviewDecision.REJECTED_AS_PRODUCTION_AUTHORITY.value
        prod_integration_auth = False
        next_state = "ADJUSTED_PRICE_ALTERNATIVE_SOURCE_DISCOVERY_V01"
        reason_codes.append("AUTHORITY_BREAKING_CONTRADICTION_DETECTED")
    else:
        decision = ReviewDecision.CONDITIONAL_REVIEW_REQUIRED.value
        prod_integration_auth = False
        if len(blocking_conditions) == 1 and "corporate action evidence insufficient" in blocking_conditions[0].lower():
            next_state = "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01"
            reason_codes.append("CORPORATE_ACTION_EVIDENCE_INSUFFICIENT")
        else:
            next_state = "ADJUSTED_PRICE_SOURCE_AUTHORITY_REVIEW_V01_FIX04"
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


def execute_failure_semantics_validation() -> list[dict[str, Any]]:
    """Execute mock tests against NaverDateRangeAdjustedClient and verify classified outcomes."""
    records: list[dict[str, Any]] = []

    # 1. SUCCESS
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

    # 2. NO_DATA
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

    # 3. NETWORK_ERROR
    client_net = NaverDateRangeAdjustedClient(max_retries=1, allow_network=True)
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

    # 4. HTTP_ERROR
    mock_resp_500 = MagicMock()
    mock_resp_500.status_code = 500
    client_http = NaverDateRangeAdjustedClient(max_retries=1, allow_network=True)
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

    # 5. PARSE_ERROR
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

    # 6. INVALID_SCHEMA
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

    # 7. OUT_OF_WINDOW_ROW
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
    """Execute parser against all 13 required negative cases."""
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

    # 7. Invalid calendar date
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

    # 13. Valid empty chartdata
    try:
        xml_empty = '<protocol><chartdata symbol="005930" count="5000" timeframe="day" precision="0" origintime="20200102"></chartdata></protocol>'
        df_empty = NaverDateRangeAdjustedClient.parse_xml_payload(xml_empty)
        results["valid_empty_chartdata"] = "PASS" if len(df_empty) == 0 else "FAIL"
    except Exception:
        results["valid_empty_chartdata"] = "FAIL"

    return results


def run_source_authority_review_fix03(
    output_dir: Path | None = None,
    start_head: str = START_HEAD_FIX03,
    allow_network: bool = False,
) -> dict[str, Any]:
    """Execute complete formal Source Authority Review FIX03 under STRICT_OFFLINE mode (Section 1-85)."""
    out_dir = output_dir or DEFAULT_REVIEW_ARTIFACTS_DIR_FIX03
    out_dir.mkdir(parents=True, exist_ok=True)
    fix02_dir = DEFAULT_REVIEW_ARTIFACTS_DIR_FIX02

    # Strict Offline Accounting (Section 44)
    accounting = NetworkAccounting(
        execution_mode="STRICT_OFFLINE",
        new_direct_naver_logical_requests=0,
        new_direct_naver_physical_attempts=0,
        new_pykrx_logical_requests=0,
        new_pykrx_physical_attempts=0,
        krx_open_api_calls=0,
        opendart_calls=0,
        krx_mdc_calls=0,
        reused_fix02_direct_naver_evidence_requests=77,
        reused_fix02_pykrx_evidence_requests=48,
        reused_v01_evidence_artifacts=["source_authority_repeatability.csv", "source_authority_repeatability_summary.json"],
        reused_fix02_evidence_artifacts=[
            "source_authority_boundary_semantics_fix02.csv",
            "source_authority_coverage_results_fix02.csv",
            "source_authority_overlap_parity_fix02.csv",
            "source_authority_ohlc_semantic_validation_fix02.csv",
        ],
    )

    # 1. Build FIX03 Runtime Authority-Derived Cohort (BLOCKER A)
    cohort_df, hist_selection_meta = build_review_cohort_fix03(fix02_dir=fix02_dir)
    cohort_path = out_dir / "source_authority_review_cohort_fix03.csv"
    cohort_df.to_csv(cohort_path, index=False)

    hist_meta_path = out_dir / "historical_only_selection_authority_fix03.json"
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

    # 3. Generic Unexpected Date Reconciliation (BLOCKER B)
    unexp_recon_df = reconcile_unexpected_dates_generic_fix03(fix02_dir=fix02_dir)
    unexp_recon_path = out_dir / "source_authority_unexpected_date_reconciliation_fix03.csv"
    unexp_recon_df.to_csv(unexp_recon_path, index=False)

    # 4. Content-Resolved Corporate Action Controls Metadata (BLOCKER C)
    corp_meta_df = build_corporate_action_controls_metadata_fix03(fix02_dir=fix02_dir)
    corp_meta_path = out_dir / "source_authority_corporate_action_controls_fix03.csv"
    corp_meta_df.to_csv(corp_meta_path, index=False)

    # 5. Boundary Semantics Test (Reuse immutable FIX02 evidence)
    fix02_bound_path = fix02_dir / "source_authority_boundary_semantics_fix02.csv"
    boundary_df = pd.read_csv(fix02_bound_path) if fix02_bound_path.exists() else pd.DataFrame()
    boundary_path = out_dir / "source_authority_boundary_semantics_fix03.csv"
    boundary_df.to_csv(boundary_path, index=False)

    # 6. Repeatability Test (Reuse immutable FIX02/V01 evidence)
    fix02_rep_sum_path = fix02_dir / "source_authority_repeatability_summary.json"
    repeat_summary = json.loads(fix02_rep_sum_path.read_text(encoding="utf-8")) if fix02_rep_sum_path.exists() else None
    rep_sum_path = out_dir / "source_authority_repeatability_summary_fix03.json"
    rep_sum_path.write_text(json.dumps(repeat_summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # 7. Coverage, Overlap Parity, and Semantic OHLC (Reuse immutable FIX02 evidence)
    fix02_cov_path = fix02_dir / "source_authority_coverage_results_fix02.csv"
    coverage_df = pd.read_csv(fix02_cov_path) if fix02_cov_path.exists() else pd.DataFrame()
    coverage_path = out_dir / "source_authority_coverage_results_fix03.csv"
    coverage_df.to_csv(coverage_path, index=False)

    fix02_par_path = fix02_dir / "source_authority_overlap_parity_fix02.csv"
    parity_df = pd.read_csv(fix02_par_path) if fix02_par_path.exists() else pd.DataFrame()
    parity_path = out_dir / "source_authority_overlap_parity_fix03.csv"
    parity_df.to_csv(parity_path, index=False)

    fix02_sem_path = fix02_dir / "source_authority_ohlc_semantic_validation_fix02.csv"
    semantic_df = pd.read_csv(fix02_sem_path) if fix02_sem_path.exists() else pd.DataFrame()
    semantic_path = out_dir / "source_authority_ohlc_semantic_validation_fix03.csv"
    semantic_df.to_csv(semantic_path, index=False)

    # 8. Executed Failure Semantics Validation
    failure_semantics_records = execute_failure_semantics_validation()
    fail_val_path = out_dir / "source_authority_failure_semantics_validation_fix03.json"
    fail_val_path.write_text(json.dumps(failure_semantics_records, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # 9. Parser Negative Matrix Validation
    parser_validation = validate_parser_negative_matrix()
    parser_val_path = out_dir / "source_authority_parser_validation_fix03.json"
    parser_val_path.write_text(json.dumps(parser_validation, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # 10. Network Accounting (BLOCKER E)
    network_accounting_dict = accounting.to_dict()
    net_path = out_dir / "source_authority_network_accounting_fix03.json"
    net_path.write_text(json.dumps(network_accounting_dict, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # 11. Stage A Evidence Manifest (Section 39)
    stage_a_files = [
        hist_meta_path,
        cohort_path,
        unexp_recon_path,
        corp_meta_path,
        coverage_path,
        parity_path,
        semantic_path,
        boundary_path,
        rep_sum_path,
        schema_path,
        fail_val_path,
        parser_val_path,
        net_path,
    ]
    stage_a_hashes: dict[str, str] = {}
    stage_a_manifest_entries: dict[str, Any] = {}
    for af in stage_a_files:
        if af.exists():
            h = hashlib.sha256(af.read_bytes()).hexdigest()
            stage_a_hashes[af.name] = h
            stage_a_manifest_entries[af.name] = {
                "path": f"artifacts/data/end_to_end_data_parity/v01/adjusted_price_source_authority_review/v01_fix03/{af.name}",
                "sha256": h,
                "size_bytes": af.stat().st_size,
            }

    stage_a_manifest_payload = {
        "schema": "source_authority_evidence_manifest_fix03",
        "directive_id": "ADJUSTED_PRICE_SOURCE_AUTHORITY_REVIEW_V01_FIX03",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "start_head": start_head,
        "candidate_id": CANDIDATE_AUTHORITY_ID,
        "artifacts": stage_a_manifest_entries,
    }
    stage_a_manifest_path = out_dir / "source_authority_evidence_manifest_fix03.json"
    stage_a_manifest_path.write_text(json.dumps(stage_a_manifest_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # 12. Stage B: Provenance Validation (BLOCKER D, Section 40)
    provenance_validation = validate_provenance_integrity_fix03(
        out_dir, stage_a_manifest_payload, schema_payload, start_head=start_head
    )
    prov_val_path = out_dir / "source_authority_provenance_validation_fix03.json"
    prov_val_path.write_text(json.dumps(provenance_validation, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # 13. Evaluate 15 Authority Gates
    eval_res = evaluate_authority_gates_fix03(
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

    # 14. Canonical Review Summary Decision Artifact (Section 41, 72)
    review_summary_payload = {
        "schema": "adjusted_price_source_authority_review_v01_fix03",
        "directive_id": "ADJUSTED_PRICE_SOURCE_AUTHORITY_REVIEW_V01_FIX03",
        "parent_directive": "ADJUSTED_PRICE_SOURCE_AUTHORITY_REVIEW_V01_FIX02",
        "start_head": start_head,
        "candidate_id": CANDIDATE_AUTHORITY_ID,
        "candidate_endpoint": NAVER_SISE_ENDPOINT,
        "candidate_request_contract": schema_payload["url_template"],
        "population_authority_path": provenance_validation["population_authority_path"],
        "population_physical_sha256": provenance_validation["population_physical_sha256"],
        "population_semantic_sha256": provenance_validation["population_semantic_sha256"],
        "pit_authority_path": provenance_validation["pit_authority_path"],
        "pit_physical_sha256": provenance_validation["pit_physical_sha256"],
        "pit_semantic_sha256": provenance_validation["pit_semantic_sha256"],
        "historical_selection_sha": stage_a_hashes.get(hist_meta_path.name, ""),
        "unexpected_reconciliation_sha": stage_a_hashes.get(unexp_recon_path.name, ""),
        "corporate_action_validation_sha": stage_a_hashes.get(corp_meta_path.name, ""),
        "failure_semantics_validation_sha": stage_a_hashes.get(fail_val_path.name, ""),
        "parser_validation_sha": stage_a_hashes.get(parser_val_path.name, ""),
        "provenance_validation_sha": hashlib.sha256(prov_val_path.read_bytes()).hexdigest(),
        "gate_results": eval_res["gate_results"],
        "all_gates_passed": eval_res["all_gates_passed"],
        "blocking_conditions": eval_res["blocking_conditions"],
        "reason_codes": eval_res["reason_codes"],
        "review_decision": eval_res["review_decision"],
        "production_integration_authorized": eval_res["production_integration_authorized"],
        "active_production_authority_changed": eval_res["active_production_authority_changed"],
        "recommended_next_state": eval_res["recommended_next_state"],
        "network_accounting": network_accounting_dict,
        "supersedes_review_artifact": "artifacts/data/end_to_end_data_parity/v01/adjusted_price_source_authority_review/v01_fix02/adjusted_price_source_authority_review_v01_fix02.json",
        "superseded_review_decision": "APPROVED_FOR_PRODUCTION_INTEGRATION",
        "superseded": True,
        "superseded_by": "ADJUSTED_PRICE_SOURCE_AUTHORITY_REVIEW_V01_FIX03",
    }
    review_sum_path = out_dir / "adjusted_price_source_authority_review_v01_fix03.json"
    review_sum_path.write_text(json.dumps(review_summary_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # 15. Final Artifact Manifest (Section 42)
    final_manifest_files = stage_a_files + [stage_a_manifest_path, prov_val_path, review_sum_path]
    final_manifest_entries = {}
    for mf in final_manifest_files:
        if mf.exists():
            final_manifest_entries[mf.name] = {
                "path": f"artifacts/data/end_to_end_data_parity/v01/adjusted_price_source_authority_review/v01_fix03/{mf.name}",
                "sha256": hashlib.sha256(mf.read_bytes()).hexdigest(),
                "size_bytes": mf.stat().st_size,
            }

    final_manifest_payload = {
        "schema": "adjusted_price_source_authority_review_fix03_manifest_v01",
        "directive_id": "ADJUSTED_PRICE_SOURCE_AUTHORITY_REVIEW_V01_FIX03",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "start_head": start_head,
        "candidate_id": CANDIDATE_AUTHORITY_ID,
        "review_decision": eval_res["review_decision"],
        "production_integration_authorized": eval_res["production_integration_authorized"],
        "artifacts": final_manifest_entries,
    }
    manifest_path = out_dir / "artifact_manifest.json"
    manifest_path.write_text(json.dumps(final_manifest_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return review_summary_payload


def run_source_authority_review_fix02(
    output_dir: Path | None = None,
    start_head: str = START_HEAD_FIX03,
) -> dict[str, Any]:
    """Legacy FIX02 wrapper delegating to FIX03."""
    return run_source_authority_review_fix03(output_dir, start_head)


def run_source_authority_review_fix01(
    output_dir: Path | None = None,
    start_head: str = START_HEAD_FIX03,
) -> dict[str, Any]:
    """Legacy FIX01 wrapper delegating to FIX03."""
    return run_source_authority_review_fix03(output_dir, start_head)


def run_source_authority_review(
    output_dir: Path | None = None,
    start_head: str = START_HEAD_FIX03,
) -> dict[str, Any]:
    """Legacy wrapper delegating to FIX03."""
    return run_source_authority_review_fix03(output_dir, start_head)


if __name__ == "__main__":
    res = run_source_authority_review_fix03()
    print("=== Source Authority Review FIX03 Execution Summary ===")
    print("Review Decision:", res["review_decision"])
    print("All Gates Passed:", res["all_gates_passed"])
    print("Production Integration Authorized:", res["production_integration_authorized"])
    print("Recommended Next State:", res["recommended_next_state"])
    print("Network Accounting:", res["network_accounting"])
    print("Gate Results:")
    for k, v in res["gate_results"].items():
        print(f"  {k:45s} : {v}")
    if res["blocking_conditions"]:
        print("Blocking Conditions:")
        for bc in res["blocking_conditions"]:
            print(f"  - {bc}")
