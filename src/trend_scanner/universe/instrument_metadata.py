"""Canonical KRX Instrument Metadata Authority.

Provides pure local, zero-network resolution of security metadata (name, listing market, asset type)
from canonical local reference authorities:
  1. data/reference/krx_instrument_metadata.parquet (or .csv)
  2. data/processed/pattern_a_universe_quality.csv
  3. PIT-bounded investability universe snapshots

Explicitly distinguishes listing market (KOSPI/KOSDAQ/KONEX) from instrument asset type (COMMON/ETF/PREFERRED/etc.)
to prevent semantic confusion and ensure fail-closed applicability handling.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
import logging
from pathlib import Path
from typing import ClassVar, Mapping

import pandas as pd

from trend_scanner.universe.models import AssetType, MarketType

logger = logging.getLogger(__name__)


def normalize_krx_market(raw_market: str | None) -> str:
    """Normalize raw KRX market string to canonical project MarketType string.

    Mapping rules (Fix Round 08 Major 2):
      - 'KOSPI' -> 'KOSPI'
      - 'KOSDAQ' -> 'KOSDAQ'
      - 'KOSDAQ GLOBAL' -> 'KOSDAQ'  (KOSDAQ market segment)
      - 'KONEX' -> 'KONEX'
      - otherwise / unknown -> 'UNKNOWN'
    """
    if raw_market is None:
        return MarketType.UNKNOWN.value
    clean = str(raw_market).strip().upper()
    if clean == MarketType.KOSPI.value:
        return MarketType.KOSPI.value
    if clean in (MarketType.KOSDAQ.value, "KOSDAQ GLOBAL"):
        return MarketType.KOSDAQ.value
    if clean == MarketType.KONEX.value:
        return MarketType.KONEX.value
    return MarketType.UNKNOWN.value


DEFAULT_BASIC_INFO_RAW_ROOT = Path(
    "data/reference/source/history/krx_instrument_master/v01/basic_info"
)
FORMAL_CLASSIFICATION_AUTHORITY = "FORMAL_SECURITY_TYPE"
FORMAL_CLASSIFICATION_UNKNOWN = "UNKNOWN"
FORMAL_CLASSIFICATION_INSUFFICIENT_IDENTITY = "INSUFFICIENT_FORMAL_IDENTITY"
FORMAL_CLASSIFICATION_UNMAPPED = "UNMAPPED_FORMAL_CATEGORY"
LEGACY_CLASSIFICATION_AUTHORITY = "LEGACY_UNVERIFIED"
MANAGED_ISSUE_SECTION = "관리종목(소속부없음)"


def map_formal_basic_info_row_to_asset_type(
    row: Mapping[str, object], *, ever_been_spac: bool = False,
) -> tuple[str, str, str, str]:
    """Map canonical KRX Basic Info formal fields to the existing asset semantics.

    The mapping is deterministic and name-independent.  ``ever_been_spac`` is
    only used for the formal managed-issue ambiguity rule already used by the
    metadata builder.
    """
    secugrp = str(row.get("SECUGRP_NM", "") or "").strip()
    sect = str(row.get("SECT_TP_NM", "") or "").strip()
    kind = str(row.get("KIND_STKCERT_TP_NM", "") or "").strip()
    isu_nm = str(row.get("ISU_NM", "") or "").strip()
    isu_eng_nm = str(row.get("ISU_ENG_NM", "") or "").strip()
    source_security_type = (
        f"SECUGRP_NM={secugrp}|SECT_TP_NM={sect}|KIND_STKCERT_TP_NM={kind}"
        f"|ISU_NM={isu_nm}|ISU_ENG_NM={isu_eng_nm}"
    )
    if "SPAC" in sect:
        return "SPAC", source_security_type, FORMAL_CLASSIFICATION_AUTHORITY, FORMAL_CLASSIFICATION_AUTHORITY
    if secugrp == "부동산투자회사":
        return "REIT", source_security_type, FORMAL_CLASSIFICATION_AUTHORITY, FORMAL_CLASSIFICATION_AUTHORITY
    if kind == "보통주":
        if sect == MANAGED_ISSUE_SECTION and ever_been_spac:
            return (
                "UNKNOWN",
                source_security_type + "|CANONICAL_HISTORY_HAS_SPAC=TRUE",
                FORMAL_CLASSIFICATION_AUTHORITY,
                FORMAL_CLASSIFICATION_INSUFFICIENT_IDENTITY,
            )
        return "COMMON", source_security_type, FORMAL_CLASSIFICATION_AUTHORITY, FORMAL_CLASSIFICATION_AUTHORITY
    if kind in ("구형우선주", "신형우선주"):
        return "PREFERRED", source_security_type, FORMAL_CLASSIFICATION_AUTHORITY, FORMAL_CLASSIFICATION_AUTHORITY
    return "UNKNOWN", source_security_type, FORMAL_CLASSIFICATION_AUTHORITY, FORMAL_CLASSIFICATION_UNMAPPED


@dataclass(frozen=True)
class InstrumentMetadata:
    """Formal instrument identification and classification record."""

    ticker: str
    name: str
    market: str
    asset_type: str
    metadata_source: str
    effective_date: str | None = None
    is_identified: bool = True
    classification_authority: str | None = None
    asset_type_source: str | None = None
    security_group: str | None = None
    listing_section: str | None = None
    security_kind: str | None = None
    source_security_type: str | None = None

    @property
    def is_common_stock(self) -> bool:
        return self.is_identified and self.asset_type == AssetType.COMMON.value

    @property
    def is_trusted_for_production(self) -> bool:
        """Production A FAST Core applicability에 asset_type을 신뢰해도 되는지.

        row가 존재하고 asset_type이 COMMON이더라도 provenance가 FORMAL_SECURITY_TYPE이
        아니면(UNKNOWN 또는 LEGACY_HEURISTIC) production에서는 신뢰하지 않는다
        (Fix Round 04 Critical 1: formal source를 증명하지 못하면 fail closed).
        """
        return (
            self.is_identified
            and self.classification_authority == "FORMAL_SECURITY_TYPE"
            and self.asset_type_source == "FORMAL_SECURITY_TYPE"
            and self.asset_type != AssetType.UNKNOWN.value
        )

    @property
    def is_common_stock_for_production(self) -> bool:
        return self.is_trusted_for_production and self.asset_type == AssetType.COMMON.value

    @property
    def is_eligible_for_historical_legacy_research(self) -> bool:
        """requested_as_of 시점이 production 신뢰 대상은 아니지만 retrospective
        연구용으로는 취급 가능한지 (Fix Round 06 Major 1, Fix Round 07 Major 1로 재정의).

        Fix Round 06은 이 판단에 "이 ticker가 requested_as_of *이후*에 실제로
        formal 재검증된 적이 있는가"(has_later_verified_snapshot)를 근거로
        사용했다. 이는 survivorship bias다 — 미래까지 살아남아 다시 검증된
        ticker만 retrospective 분석이 가능해지고, 상장폐지되어 다시 검증될
        기회가 없었던 ticker(예: 380440)는 동일한 품질의 historical metadata를
        가지고도 부당하게 배제된다. 또한 이 판단 자체가 미래 시점의 정보를
        과거 시점 조회의 eligibility 결정에 사용하는 것이라 Strict PIT 정신에도
        어긋난다.

        Fix Round 07부터 이 판단은 오직 **선택된(selected) PIT row 자체의 값**만
        본다 — 미래의 다른 row는 전혀 조회하지 않는다: classification_authority와
        asset_type_source가 둘 다 정확히 "LEGACY_UNVERIFIED"이고(다른 종류의
        untrusted provenance, 예: LEGACY_HEURISTIC/NAME_BASED_HEURISTIC은 여기
        해당하지 않는다 — 그런 row는 애초에 formal frozen PIT snapshot이 아니라
        신뢰도가 다른 heuristic 추정치이므로 승격 금지), asset_type이 UNKNOWN이
        아니면 historical retrospective 연구 대상으로 인정한다.
        """
        return (
            self.is_identified
            and self.classification_authority == "LEGACY_UNVERIFIED"
            and self.asset_type_source == "LEGACY_UNVERIFIED"
            and self.asset_type != AssetType.UNKNOWN.value
        )


def _normalise_target_ticker(value: object) -> str:
    return str(value or "").strip().upper().zfill(6)


def _target_date(value: str) -> str:
    parsed = pd.Timestamp(str(value).strip()[:10])
    return parsed.strftime("%Y-%m-%d")


def resolve_basic_info_snapshot_dir(
    repo_root: Path | str, target_as_of: str,
) -> tuple[Path, str]:
    """Resolve the exact or latest-past canonical Basic Info snapshot."""
    root = Path(repo_root)
    target = _target_date(target_as_of).replace("-", "")
    basic_root = root / DEFAULT_BASIC_INFO_RAW_ROOT
    candidates = sorted(
        (path for path in basic_root.glob("*/*") if path.is_dir() and path.name.isdigit() and len(path.name) == 8),
        key=lambda path: path.name,
    )
    past = [path for path in candidates if path.name <= target]
    if not past:
        raise FileNotFoundError(
            f"no canonical Basic Info snapshot on or before target {target_as_of}: {basic_root}"
        )
    chosen = past[-1]
    return chosen, f"{chosen.name[:4]}-{chosen.name[4:6]}-{chosen.name[6:]}"


@lru_cache(maxsize=8)
def _historical_spac_tickers(repo_root_str: str, cutoff: str) -> frozenset[str]:
    """Return formal SPAC tickers observed on or before ``cutoff``.

    The cache is per repository/cutoff and is intentionally read-only.  It keeps
    the managed-issue rule deterministic without consulting the frozen metadata
    artifact or using name heuristics.
    """
    basic_root = Path(repo_root_str) / DEFAULT_BASIC_INFO_RAW_ROOT
    spac: set[str] = set()
    for path in basic_root.glob("*/*/*.json"):
        date_token = path.parent.name
        if len(date_token) != 8 or not date_token.isdigit() or date_token > cutoff.replace("-", ""):
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        for row in payload.get("OutBlock_1", []):
            section = str(row.get("SECT_TP_NM", "") or "").strip()
            ticker = _normalise_target_ticker(row.get("ISU_SRT_CD"))
            if ticker and len(ticker) == 6 and "SPAC" in section:
                spac.add(ticker)
    return frozenset(spac)


@lru_cache(maxsize=8)
def _load_target_basic_info_records_cached(
    repo_root_str: str, target_as_of: str,
) -> tuple[tuple[dict[str, object], ...], str]:
    root = Path(repo_root_str)
    snapshot_dir, snapshot_date = resolve_basic_info_snapshot_dir(root, target_as_of)
    historical_spac = _historical_spac_tickers(repo_root_str, snapshot_date)
    records: list[dict[str, object]] = []
    seen: set[str] = set()
    for market_file in ("KOSPI.json", "KOSDAQ.json"):
        path = snapshot_dir / market_file
        if not path.exists():
            raise FileNotFoundError(f"canonical Basic Info market snapshot missing: {path}")
        payload = json.loads(path.read_text(encoding="utf-8"))
        for raw in payload.get("OutBlock_1", []):
            ticker = _normalise_target_ticker(raw.get("ISU_SRT_CD"))
            if not ticker or len(ticker) != 6:
                continue
            if ticker in seen:
                raise ValueError(f"duplicate canonical Basic Info ticker: {ticker}")
            seen.add(ticker)
            asset_type, source_security_type, authority, asset_source = map_formal_basic_info_row_to_asset_type(
                raw, ever_been_spac=ticker in historical_spac,
            )
            records.append({
                "ticker": ticker,
                "name": str(raw.get("ISU_ABBRV") or raw.get("ISU_NM") or ticker).strip(),
                "market": normalize_krx_market(raw.get("MKT_TP_NM")),
                "asset_type": asset_type,
                "metadata_source": "KRX_BASIC_INFO_CANONICAL",
                "effective_date": snapshot_date,
                "classification_authority": authority,
                "asset_type_source": asset_source,
                "source_security_type": source_security_type,
                "security_group": str(raw.get("SECUGRP_NM") or "").strip(),
                "listing_section": str(raw.get("SECT_TP_NM") or "").strip(),
                "security_kind": str(raw.get("KIND_STKCERT_TP_NM") or "").strip(),
            })
    records.sort(key=lambda item: str(item["ticker"]))
    return tuple(records), snapshot_date


def load_target_basic_info_universe(
    repo_root: Path | str, target_as_of: str,
) -> tuple[list[dict[str, object]], str]:
    """Load target-scoped KOSPI/KOSDAQ Basic Info rows and formal classification."""
    records, snapshot_date = _load_target_basic_info_records_cached(
        str(Path(repo_root).resolve()), _target_date(target_as_of),
    )
    return [dict(record) for record in records], snapshot_date


def resolve_target_instrument_metadata(
    ticker: str, *, as_of: str, repo_root: Path | str,
) -> InstrumentMetadata:
    """Resolve equity identity/classification from target canonical Basic Info."""
    clean_ticker = _normalise_target_ticker(ticker)
    records, _snapshot_date = _load_target_basic_info_records_cached(
        str(Path(repo_root).resolve()), _target_date(as_of),
    )
    for row in records:
        if row["ticker"] != clean_ticker:
            continue
        return InstrumentMetadata(
            ticker=clean_ticker,
            name=str(row["name"]),
            market=str(row["market"]),
            asset_type=str(row["asset_type"]),
            metadata_source=str(row["metadata_source"]),
            effective_date=str(row["effective_date"]),
            is_identified=True,
            classification_authority=str(row["classification_authority"]),
            asset_type_source=str(row["asset_type_source"]),
            security_group=str(row["security_group"]),
            listing_section=str(row["listing_section"]),
            security_kind=str(row["security_kind"]),
            source_security_type=str(row["source_security_type"]),
        )
    return InstrumentMetadata(
        ticker=clean_ticker,
        name=clean_ticker,
        market=MarketType.UNKNOWN.value,
        asset_type=AssetType.UNKNOWN.value,
        metadata_source="TARGET_BASIC_INFO_UNAVAILABLE",
        effective_date=None,
        is_identified=False,
        classification_authority=FORMAL_CLASSIFICATION_UNKNOWN,
        asset_type_source=FORMAL_CLASSIFICATION_UNKNOWN,
    )


def load_target_production_universe(
    repo_root: Path | str, target_as_of: str,
) -> tuple[list[dict[str, object]], str]:
    """Build the shared target production universe.

    Current KOSPI/KOSDAQ equity rows come only from target Basic Info.  Existing
    ETF/ETN rows retain their established product-master metadata contract.
    """
    root = Path(repo_root)
    target_rows, snapshot_date = load_target_basic_info_universe(root, target_as_of)
    existing = InstrumentMetadataResolver.load_master_dataframe(root).copy()
    product_rows: list[dict[str, object]] = []
    if not existing.empty and {"ticker", "effective_date", "asset_type"}.issubset(existing.columns):
        frame = existing.copy()
        frame["ticker"] = frame["ticker"].map(_normalise_target_ticker)
        frame["effective_date"] = pd.to_datetime(frame["effective_date"], errors="coerce")
        eligible = frame[
            frame["effective_date"].notna()
            & (frame["effective_date"] <= pd.Timestamp(_target_date(target_as_of)))
        ]
        if not eligible.empty:
            latest = eligible["effective_date"].max()
            current = eligible[eligible["effective_date"] == latest]
            target_tickers = {str(row["ticker"]) for row in target_rows}
            for row in current.to_dict(orient="records"):
                asset_type = str(row.get("asset_type") or "UNKNOWN").strip().upper()
                if asset_type not in {"ETF", "ETN"} or str(row["ticker"]) in target_tickers:
                    continue
                product_rows.append({
                    "ticker": str(row["ticker"]),
                    "name": str(row.get("name") or row["ticker"]).strip(),
                    "market": str(row.get("market") or "UNKNOWN").strip().upper(),
                    "asset_type": asset_type,
                    "effective_date": str(row["effective_date"].date()),
                    "classification_authority": str(row.get("classification_authority") or FORMAL_CLASSIFICATION_UNKNOWN),
                    "asset_type_source": str(row.get("asset_type_source") or FORMAL_CLASSIFICATION_UNKNOWN),
                    "metadata_source": str(row.get("metadata_source") or "LOCAL_PRODUCT_METADATA"),
                })
    combined = target_rows + product_rows
    combined.sort(key=lambda item: str(item["ticker"]))
    if len({str(item["ticker"]) for item in combined}) != len(combined):
        raise ValueError("target production universe contains duplicate tickers")
    return combined, snapshot_date


def load_target_pit_common_tickers(
    repo_root: Path | str, target_as_of: str,
) -> set[str]:
    """Return target PIT COMMON tickers that pass formal target classification."""
    root = Path(repo_root)
    pit_path = root / "data/market/rolling_authority/merged_pit_intervals.json"
    if not pit_path.exists():
        raise FileNotFoundError(f"merged PIT authority missing: {pit_path}")
    target = _target_date(target_as_of)
    records, _snapshot_date = _load_target_basic_info_records_cached(
        str(root.resolve()), target,
    )
    metadata_by_ticker = {str(row["ticker"]): row for row in records}
    payload = json.loads(pit_path.read_text(encoding="utf-8"))
    return {
        str(interval["ticker"]).strip().upper()
        for interval in payload.get("intervals", [])
        if interval.get("state") == "COMMON"
        and str(interval.get("effective_from", "")) <= target <= str(interval.get("effective_to", ""))
        and str(interval.get("market", "")).upper() in {"KOSPI", "KOSDAQ"}
        and bool(metadata_by_ticker.get(str(interval["ticker"]).strip().upper(), {}).get("asset_type") == "COMMON")
        and metadata_by_ticker.get(str(interval["ticker"]).strip().upper(), {}).get("classification_authority") == FORMAL_CLASSIFICATION_AUTHORITY
        and metadata_by_ticker.get(str(interval["ticker"]).strip().upper(), {}).get("asset_type_source") == FORMAL_CLASSIFICATION_AUTHORITY
    }


class InstrumentMetadataResolver:
    """Memoized local instrument metadata resolver with Strict PIT guarantee."""

    _cached_df: ClassVar[pd.DataFrame | None] = None
    _cached_repo_root: ClassVar[Path | None] = None

    @classmethod
    def clear_cache(cls) -> None:
        """Clear memoized master dataframe (useful for testing fixture isolation)."""
        cls._cached_df = None
        cls._cached_repo_root = None

    @classmethod
    def load_master_dataframe(cls, repo_root: Path | None = None) -> pd.DataFrame:
        root = repo_root or Path.cwd()
        if cls._cached_df is not None and cls._cached_repo_root == root:
            return cls._cached_df

        # 1. Primary: data/reference/krx_instrument_metadata.parquet
        pq_path = root / "data/reference/krx_instrument_metadata.parquet"
        csv_ref_path = root / "data/reference/krx_instrument_metadata.csv"
        quality_csv = root / "data/processed/pattern_a_universe_quality.csv"

        df: pd.DataFrame | None = None
        if pq_path.exists():
            try:
                df = pd.read_parquet(pq_path)
            except Exception as exc:
                logger.warning("Failed reading %s: %s", pq_path, exc)

        if df is None and csv_ref_path.exists():
            try:
                df = pd.read_csv(csv_ref_path, dtype={"ticker": str})
            except Exception as exc:
                logger.warning("Failed reading %s: %s", csv_ref_path, exc)

        if df is None and quality_csv.exists():
            try:
                df = pd.read_csv(quality_csv, dtype={"ticker": str})
                if "classification_authority" not in df.columns:
                    df["classification_authority"] = "LEGACY_HEURISTIC"
                if "asset_type_source" not in df.columns:
                    df["asset_type_source"] = "NAME_BASED_HEURISTIC"
                if "metadata_source" not in df.columns:
                    df["metadata_source"] = "LEGACY_QUALITY_DIAGNOSTIC"
            except Exception as exc:
                logger.warning("Failed reading %s: %s", quality_csv, exc)

        if df is not None:
            df = df.copy()
            df["ticker"] = df["ticker"].astype(str).str.strip().str.zfill(6)
            if "effective_date" not in df.columns:
                df["effective_date"] = None
            cls._cached_df = df
            cls._cached_repo_root = root
            return df

        return pd.DataFrame(columns=["ticker", "name", "market", "asset_type", "metadata_source", "effective_date", "classification_authority", "asset_type_source"])

    @classmethod
    def resolve(
        cls,
        ticker: str,
        as_of: str | None = None,
        repo_root: Path | None = None,
    ) -> InstrumentMetadata:
        """Resolve instrument metadata ensuring Strict PIT (effective_date <= requested_as_of)."""
        clean_ticker = str(ticker).strip().zfill(6)
        as_of_str = str(as_of).strip()[:10] if as_of else None
        df_master = cls.load_master_dataframe(repo_root)

        if not df_master.empty:
            matches = df_master[df_master["ticker"] == clean_ticker]
            if not matches.empty:
                # Enforce Strict PIT on metadata effective date:
                # Reject future metadata if requested_as_of is specified.
                if as_of_str is not None and "effective_date" in matches.columns:
                    past_matches = matches[
                        matches["effective_date"].notna()
                        & (matches["effective_date"].astype(str).str[:10] <= as_of_str)
                    ]
                else:
                    past_matches = matches

                # Fix Round 07 Major 1: HISTORICAL_LEGACY_RESEARCH eligibility는 selected
                # row 자체의 provenance만으로 결정한다 (is_eligible_for_historical_legacy_research
                # 참고) — requested_as_of 이후의 다른 row를 조회하는 future lookup은 여기서도,
                # 다른 어디에서도 수행하지 않는다 (survivorship bias 제거, Strict PIT 유지).
                if not past_matches.empty:
                    # Select latest snapshot not after requested_as_of
                    row = past_matches.sort_values(by="effective_date", ascending=True).iloc[-1]
                    name = str(row["name"]).strip() if "name" in row and not pd.isna(row["name"]) else clean_ticker
                    raw_market = row.get("market") if "market" in row and not pd.isna(row["market"]) else None
                    market = normalize_krx_market(raw_market)
                    asset_type = str(row["asset_type"]).strip().upper() if "asset_type" in row and not pd.isna(row["asset_type"]) else "UNKNOWN"
                    source = str(row["metadata_source"]).strip() if "metadata_source" in row and not pd.isna(row["metadata_source"]) else "LOCAL_AUTHORITY"
                    eff_date = str(row["effective_date"]).strip() if "effective_date" in row and not pd.isna(row["effective_date"]) else as_of_str
                    auth = str(row["classification_authority"]).strip() if ("classification_authority" in row and not pd.isna(row["classification_authority"])) else "UNKNOWN"
                    asset_source = str(row["asset_type_source"]).strip() if ("asset_type_source" in row and not pd.isna(row["asset_type_source"])) else "UNKNOWN"

                    # Normalization
                    if asset_type not in [a.value for a in AssetType]:
                        asset_type = AssetType.UNKNOWN.value

                    return InstrumentMetadata(
                        ticker=clean_ticker,
                        name=name,
                        market=market,
                        asset_type=asset_type,
                        metadata_source=source,
                        effective_date=eff_date,
                        is_identified=True,
                        classification_authority=auth,
                        asset_type_source=asset_source,
                    )

        # Fail closed: metadata unavailable or all available metadata is in the future
        return InstrumentMetadata(
            ticker=clean_ticker,
            name=clean_ticker,
            market=MarketType.UNKNOWN.value,
            asset_type=AssetType.UNKNOWN.value,
            metadata_source="METADATA_UNAVAILABLE",
            effective_date=None,
            is_identified=False,
            classification_authority="UNKNOWN",
            asset_type_source="UNKNOWN",
        )


def resolve_instrument_metadata(
    ticker: str,
    as_of: str | None = None,
    repo_root: Path | None = None,
) -> InstrumentMetadata:
    """Convenience helper to resolve instrument metadata."""
    return InstrumentMetadataResolver.resolve(ticker=ticker, as_of=as_of, repo_root=repo_root)
