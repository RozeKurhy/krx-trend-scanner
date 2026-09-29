#!/usr/bin/env python3
"""Select one liquid, plain-long representative ETF per broad exposure group."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "artifacts/research/etf_official_universe_refinement_v02"
DEFAULT_MASTER = DEFAULT_OUTPUT / "all_current_etf_snapshot.csv"
FALLBACK_MASTER = ROOT / "artifacts/research/etf_plain_long_market_sector_resource_v05/krx_etf_product_metadata_2026-09-29.csv"
DEFAULT_RANKING = ROOT / "web/data/etf-ranking.json"
SOURCE_NAME = "KRX MDC ETF_전종목기본종목"
NEAR_TURNOVER_RELATIVE_TOLERANCE = 0.01

_STRUCTURE_EXCLUSIONS = (
    (re.compile(r"레버리지|인버스|inverse|leverage|\bshort\b|\bbear\b|\b2x\b|\b3x\b|2배|3배", re.I), "LEVERAGE_INVERSE_OR_SHORT"),
    (re.compile(r"커버드.?콜|covered.?call|buy.?write|콜매도|옵션.?인컴|옵션.?프리미엄|option.?income|option.?premium", re.I), "COVERED_CALL_OR_OPTION_INCOME"),
    (re.compile(r"buffer|버퍼|defined.?outcome|목표헤지", re.I), "BUFFERED_OR_DEFINED_OUTCOME"),
    (re.compile(r"채권|국채|회사채|단기채|초단기|머니마켓|KOFR|CD금리|SOFR|금리|\bbond\b|\btreasury\b|money.?market", re.I), "FIXED_INCOME_RATE_OR_CASH"),
    (re.compile(r"혼합자산|blend|blended|혼합지수|\b50\s*/\s*50\b|\b70\s*/\s*30\b|\b30\s*/\s*70\b", re.I), "MIXED_ASSET_OR_COMPOSITE_PAYOFF"),
    (re.compile(r"리츠|\bREIT\b|real.?estate", re.I), "PROPERTY_OR_REIT"),
    (re.compile(r"고배당|배당주|배당|dividend|covered.?income|인컴", re.I), "DIVIDEND_OR_INCOME_STYLE"),
    (re.compile(r"밸류업|가치주|성장주|그로스|저변동|최소변동|low.?vol|quality|퀄리티|동일가중|equal.?weight|모멘텀|momentum|팩터|factor|ESG|기후|탄소|주주환원|자사주", re.I), "STYLE_OR_FACTOR"),
)
_NARROW_THEME = re.compile(
    r"(?<![A-Za-z])AI(?![A-Za-z])|인공지능|로봇|robot|양자|quantum|전기차|electric.?vehicle|수소경제|수소연료|hydrogen|"
    r"원자력|원전|nuclear|신재생|renewable|태양광|solar|풍력|wind|우주|space|위성|satellite|"
    r"메타버스|metaverse|블록체인|blockchain|테마|thematic|포커스|\bfocus\b|밸류체인|value.?chain|TOP\s*\d+|엔비디아|nvidia|테슬라|tesla",
    re.I,
)
_TOP_N = re.compile(r"\bTOP\s*(\d+)\b|TOP(\d+)", re.I)


def _text(row: dict[str, Any], *fields: str) -> str:
    return " ".join(str(row.get(field, "") or "") for field in fields).strip()


def _market_group(objective: str) -> str | None:
    value = objective.lower().replace(" ", "")
    if re.search(r"코스닥(?:150|글로벌)?|kosdaq(?:150|global)?", value):
        return "KOSDAQ_BROAD"
    if re.search(r"코스피(?:200|100|50|tr)?|kospi(?:200|100|50|tr)?|krx(?:300|100|200)|msci.?korea", value):
        return "KOREA_BROAD"
    if re.search(r"nasdaq100|나스닥100", value):
        return "NASDAQ_100"
    if re.search(r"s\&?p500|s&p500|msci.?usa|dow.?jones|djia|russell1000|ftse.?usa", value):
        return "US_BROAD"
    if re.search(r"msci.?world|msci.?acwi|ftse.?all.?world|global.?all.?cap", value):
        return "GLOBAL_BROAD"
    if re.search(r"msci.?em(?:erging)?|ftse.?emerging", value):
        return "EMERGING_MARKETS"
    if re.search(r"nikkei.?225|topix|msci.?japan", value):
        return "JAPAN_BROAD"
    if re.search(r"csi(?:300|500|1000|a50|a100)|msci.?china|hang.?seng(?!tech)|hscei", value):
        return "CHINA_BROAD"
    if re.search(r"nifty.?50|msci.?india|india.?large.?cap", value):
        return "INDIA_BROAD"
    country_patterns = (
        (r"vn30|vietnam", "VIETNAM_BROAD"),
        (r"msci.?indonesia|indonesia", "INDONESIA_BROAD"),
        (r"taiwan.?weighted|taiex|msci.?taiwan", "TAIWAN_BROAD"),
        (r"euro.?stoxx|stoxx.?europe|dax.?40|cac.?40|msci.?europe", "EUROPE_BROAD"),
        (r"ibovespa|brazil", "BRAZIL_BROAD"),
        (r"msci.?thailand|thailand", "THAILAND_BROAD"),
        (r"msci.?malaysia|malaysia", "MALAYSIA_BROAD"),
        (r"msci.?singapore|singapore", "SINGAPORE_BROAD"),
        (r"msci.?mexico|mexico", "MEXICO_BROAD"),
        (r"msci.?germany|dax", "GERMANY_BROAD"),
        (r"msci.?france|cac", "FRANCE_BROAD"),
        (r"msci.?australia|asx.?200", "AUSTRALIA_BROAD"),
        (r"msci.?philippines|philippines", "PHILIPPINES_BROAD"),
    )
    for pattern, group in country_patterns:
        if re.search(pattern, value):
            return group
    return None


def _sector_group(text: str) -> str | None:
    rules = (
        (r"반도체|semiconductor|\bsemi\b", "SEMICONDUCTOR"),
        (r"2차전지|배터리|battery", "SECONDARY_BATTERY"),
        (r"은행|\bbank(?:ing)?\b", "BANK"),
        (r"증권|securities|brokerage", "SECURITIES"),
        (r"보험|insurance", "INSURANCE"),
        (r"금융|financial", "FINANCIALS"),
        (r"자동차|자동차부품|automotive|\bauto\b|mobility", "AUTO"),
        (r"건설|construction", "CONSTRUCTION"),
        (r"철강|steel", "STEEL"),
        (r"헬스케어|health.?care|healthcare|바이오|biotech|biotechnology|제약|pharma|의료", "HEALTHCARE"),
        (r"소프트웨어|software", "SOFTWARE"),
        (r"에너지.?화학", "ENERGY_CHEMICALS"),
        (r"화학|chemical", "CHEMICALS"),
        (r"에너지|energy|oil.?and.?gas|oil.?\&.?gas", "ENERGY"),
        (r"중공업|조선|shipbuilding|heavy.?industry|machinery|기계장비", "HEAVY_INDUSTRY"),
        (r"필수소비재|consumer.?staples|food.?\&.?beverage|식품|음식료", "CONSUMER_STAPLES"),
        (r"경기소비재|consumer.?discretionary|유통|retail", "CONSUMER_DISCRETIONARY"),
        (r"화장품|cosmetics", "COSMETICS"),
        (r"운송|운수|transport|항공|airline|해운|shipping", "TRANSPORTATION"),
        (r"여행레저|travel.?leisure|호텔|hotel", "TRAVEL_LEISURE"),
        (r"방산|방위산업|defen[cs]e|aerospace", "DEFENSE_AEROSPACE"),
        (r"전력기기|전력설비|전기.?기기|power.?equipment|electrical.?equipment|전력", "POWER_EQUIPMENT"),
        (r"정보기술|\bIT\b|technology|\btech\b|인터넷|internet|커뮤니케이션서비스|communication", "INFORMATION_TECHNOLOGY"),
        (r"게임|gaming|game.?industry", "GAMING"),
        (r"미디어|콘텐츠|엔터|media|entertainment|\bK.?POP\b", "MEDIA_ENTERTAINMENT"),
        (r"철도|railway|infrastructure|인프라", "INFRASTRUCTURE"),
        (r"농업|agriculture|농산", "AGRICULTURE_INDUSTRY"),
        (r"산업재|유틸리티|utilities", "INDUSTRIALS_UTILITIES"),
    )
    for pattern, group in rules:
        if re.search(pattern, text, re.I):
            return group
    return None


def classify_product(row: dict[str, Any]) -> dict[str, str]:
    """Classify one official KRX ETF row using broad mandate and structure rules."""
    name = str(row.get("ISU_ABBRV", "")).strip()
    objective = str(row.get("ETF_OBJ_IDX_NM", "")).strip()
    asset = str(row.get("IDX_ASST_CLSS_NM", "")).strip()
    text = _text(row, "ISU_NM", "ISU_ABBRV", "ISU_ENG_NM", "ETF_OBJ_IDX_NM")

    if asset == "채권":
        return {"major_category": "OUT_OF_SCOPE", "representative_group": "", "product_structure": "OUT_OF_SCOPE", "classification_reason": "FIXED_INCOME_RATE_OR_CASH"}
    if asset == "혼합자산":
        return {"major_category": "OUT_OF_SCOPE", "representative_group": "", "product_structure": "OUT_OF_SCOPE", "classification_reason": "MIXED_ASSET"}
    if asset == "통화":
        return {"major_category": "OUT_OF_SCOPE", "representative_group": "", "product_structure": "OUT_OF_SCOPE", "classification_reason": "CURRENCY_EXPOSURE"}
    if asset == "부동산" or re.search(r"리츠|\bREIT\b|real.?estate", text, re.I):
        return {"major_category": "OUT_OF_SCOPE", "representative_group": "", "product_structure": "OUT_OF_SCOPE", "classification_reason": "PROPERTY_OR_REIT"}
    for pattern, reason in _STRUCTURE_EXCLUSIONS:
        if pattern.search(text):
            return {"major_category": "OUT_OF_SCOPE", "representative_group": "", "product_structure": "OUT_OF_SCOPE", "classification_reason": reason}
    if asset == "원자재":
        commodity_rules = (
            (r"금(?:현물|선물)|골드|gold", "GOLD"), (r"은(?:현물|선물)|실버|silver", "SILVER"),
            (r"원유|crude|\bwti\b|\bbrent\b", "CRUDE_OIL"),
            (r"구리|copper", "COPPER"), (r"콩|soybean|농산|곡물|grains", "AGRICULTURE"),
            (r"천연가스|natural.?gas", "NATURAL_GAS"),
            (r"팔라듐|palladium", "PALLADIUM"), (r"백금|platinum", "PLATINUM"),
        )
        for pattern, group in commodity_rules:
            if re.search(pattern, text, re.I):
                kind = "SPOT" if re.search(r"현물|실물|\bspot\b|cash copper", text, re.I) else "FUTURES" if re.search(r"선물|future|\bER\b", text, re.I) else "OTHER"
                return {"major_category": "COMMODITY_RESOURCE", "representative_group": group, "product_structure": f"PLAIN_LONG_{kind}", "classification_reason": "CLEAR_SINGLE_COMMODITY_EXPOSURE"}
        return {"major_category": "OUT_OF_SCOPE", "representative_group": "", "product_structure": "OUT_OF_SCOPE", "classification_reason": "UNMAPPED_COMMODITY_EXPOSURE"}

    if asset != "주식":
        return {"major_category": "OUT_OF_SCOPE", "representative_group": "", "product_structure": "OUT_OF_SCOPE", "classification_reason": "OTHER_ASSET_CLASS"}

    # TOP-N concentration and specific themes are out of scope even when their
    # marketing/index text contains a broad sector keyword.
    top_n = _TOP_N.search(text)
    if top_n and int(top_n.group(1) or top_n.group(2)) <= 20:
        return {"major_category": "OUT_OF_SCOPE", "representative_group": "", "product_structure": "OUT_OF_SCOPE", "classification_reason": "CONCENTRATED_TOP_N"}
    if _NARROW_THEME.search(text):
        return {"major_category": "OUT_OF_SCOPE", "representative_group": "", "product_structure": "OUT_OF_SCOPE", "classification_reason": "NARROW_THEME_OR_VALUE_CHAIN"}

    sector_group = _sector_group(f"{name} {objective}")
    if sector_group:
        return {"major_category": "SECTOR_INDEX", "representative_group": sector_group, "product_structure": "PLAIN_LONG", "classification_reason": f"BROAD_SECTOR_INDEX:{objective}"}
    market_group = _market_group(objective)
    if market_group:
        return {"major_category": "MARKET_INDEX", "representative_group": market_group, "product_structure": "PLAIN_LONG", "classification_reason": f"BROAD_MARKET_INDEX:{objective}"}
    return {"major_category": "OUT_OF_SCOPE", "representative_group": "", "product_structure": "OUT_OF_SCOPE", "classification_reason": "NO_CLEAR_BROAD_MARKET_SECTOR_OR_COMMODITY_GROUP"}


def select_group_representatives(candidates: pd.DataFrame) -> pd.DataFrame:
    """Choose one turnover leader per group; prefer a passing spot commodity."""
    if candidates.empty:
        return candidates.copy()
    selected: list[pd.Series] = []
    for (_category, _group), group in candidates.groupby(["major_category", "representative_group"], sort=True):
        pool = group
        if _category == "COMMODITY_RESOURCE" and group["product_structure"].eq("PLAIN_LONG_SPOT").any():
            pool = group[group["product_structure"].eq("PLAIN_LONG_SPOT")]
        ordered = pool.sort_values(
            ["avg_trading_value_40d", "AUM_if_available", "listing_age_days", "ticker"],
            ascending=[False, False, False, True], kind="mergesort", na_position="last",
        )
        top_turnover = float(ordered.iloc[0]["avg_trading_value_40d"])
        near = ordered.loc[
            ordered["avg_trading_value_40d"] >= top_turnover * (1.0 - NEAR_TURNOVER_RELATIVE_TOLERANCE)
        ]
        used_aum_tie_break = len(near) > 1
        if used_aum_tie_break:
            near = near.sort_values(
                ["AUM_if_available", "listing_age_days", "avg_trading_value_40d", "ticker"],
                ascending=[False, False, False, True], kind="mergesort", na_position="last",
            )
            winner = near.iloc[0].copy()
        else:
            winner = ordered.iloc[0].copy()
        reason_parts = []
        if _category == "COMMODITY_RESOURCE" and winner["product_structure"] == "PLAIN_LONG_SPOT":
            reason_parts.append("Spot product preferred over futures.")
        if used_aum_tie_break:
            reason_parts.append("Candidate turnover was within 1%; largest available AUM selected, then listing age.")
        else:
            reason_parts.append("Highest 40D average trading value; AUM and listing age break ties.")
        winner["selection_reason"] = " ".join(reason_parts)
        selected.append(winner)
    return pd.DataFrame(selected).reset_index(drop=True)


def hard_filter_failures(row: Any, reference_date: str | pd.Timestamp) -> list[str]:
    """Return every failed scope/liquidity gate without filling missing data."""
    result: list[str] = []
    if row["major_category"] == "OUT_OF_SCOPE" or not str(row["representative_group"]):
        return [str(row["classification_reason"])]
    ref = pd.Timestamp(reference_date)
    listing = pd.to_datetime(row["listing_date"], errors="coerce")
    if pd.isna(listing) or listing + pd.DateOffset(years=2) > ref:
        result.append("LISTING_AGE_LT_2Y")
    if pd.isna(row["reference_close"]):
        result.append("MISSING_REFERENCE_DATE_CLOSE")
    elif float(row["reference_close"]) < 1000:
        result.append("REFERENCE_CLOSE_LT_1000_KRW")
    raw_session_count = row["raw_session_count_40d"]
    if pd.isna(raw_session_count) or int(raw_session_count) != 40 or pd.isna(row["avg_volume_40d"]):
        result.append("INCOMPLETE_EXACT_40D_RAW_SESSIONS")
    elif float(row["avg_volume_40d"]) < 10000:
        result.append("AVG_VOLUME_40D_LT_10000_SHARES")
    if pd.isna(row["avg_trading_value_40d"]):
        if "INCOMPLETE_EXACT_40D_RAW_SESSIONS" not in result:
            result.append("MISSING_40D_AVG_TRADING_VALUE")
    elif float(row["avg_trading_value_40d"]) < 300_000_000:
        result.append("AVG_TRADING_VALUE_40D_LT_300M_KRW")
    return result


def compare_ranking24(classified: pd.DataFrame, selected: pd.DataFrame, ranking: dict[str, Any]) -> pd.DataFrame:
    current = classified.set_index("ticker", drop=False)
    ranking_items = ranking.get("items", [])
    if len(ranking_items) != 24 or len({str(row.get("ticker", "")) for row in ranking_items}) != 24:
        raise ValueError("EXISTING_RANKING_24_INVALID")
    rank_by_group: dict[tuple[str, str], list[str]] = {}
    ungrouped: list[tuple[str, str]] = []
    for item in ranking_items:
        ticker = str(item["ticker"])
        if ticker not in current.index:
            ungrouped.append((ticker, "RANKING_TICKER_NOT_IN_CURRENT_KRX_UNIVERSE"))
            continue
        row = current.loc[ticker]
        key = (str(row["major_category"]), str(row["representative_group"]))
        if key[1]:
            rank_by_group.setdefault(key, []).append(ticker)
        else:
            ungrouped.append((ticker, str(row["classification_reason"])))
    selected_by_group = {
        (str(row.major_category), str(row.representative_group)): str(row.ticker)
        for row in selected.itertuples(index=False)
    }
    keys = sorted(set(rank_by_group) | set(selected_by_group))
    rows: list[dict[str, Any]] = []
    for category, group in keys:
        rank_tickers = sorted(rank_by_group.get((category, group), []))
        ticker = selected_by_group.get((category, group), "")
        if not ticker:
            status = "NO_ELIGIBLE_REPRESENTATIVE"
        elif ticker in rank_tickers:
            status = "RETAINED_FROM_RANKING_24"
        elif rank_tickers:
            status = "REPLACED_RANKING_24_MEMBER"
        else:
            status = "NEWLY_SELECTED_OUTSIDE_RANKING_24"
        rows.append({
            "major_category": category, "representative_group": group,
            "existing_ranking_24_tickers": "|".join(rank_tickers),
            "selected_ticker": ticker, "selected_in_ranking_24": bool(ticker and ticker in rank_tickers),
            "comparison_status": status,
        })
    for ticker, reason in ungrouped:
        rows.append({
            "major_category": "OUT_OF_SCOPE", "representative_group": f"UNMAPPED_RANKING_TICKER_{ticker}",
            "existing_ranking_24_tickers": ticker, "selected_ticker": "",
            "selected_in_ranking_24": False,
            "comparison_status": f"NO_ELIGIBLE_REPRESENTATIVE:{reason}",
        })
    return pd.DataFrame(rows).sort_values(["major_category", "representative_group"], kind="mergesort").reset_index(drop=True)


def _load_market_rows(root: Path, *, ranking_path: Path) -> tuple[str, list[str], pd.DataFrame, dict[str, Any]]:
    from trend_scanner.data.krx_raw_stock_store import KrxRawStockStore
    from trend_scanner.data.market_calendar import load_rolling_production_market_calendar

    store = KrxRawStockStore(root / "data/market/raw/krx_stocks/v01")
    complete = [row["date"] for row in store.list_manifest("ETF") if row["status"] == "COMPLETE"]
    calendar = load_rolling_production_market_calendar(root)
    calendar_dates = {pd.Timestamp(value).strftime("%Y-%m-%d") for value in calendar.trading_dates}
    usable = sorted(day for day in complete if day in calendar_dates)
    if not usable:
        raise RuntimeError("NO_KRX_ETF_RAW_DATE_IN_CANONICAL_CALENDAR")
    reference_date = usable[-1]
    dates = [pd.Timestamp(value).strftime("%Y-%m-%d") for value in calendar.trading_dates if pd.Timestamp(value) <= pd.Timestamp(reference_date)][-40:]
    if len(dates) != 40 or dates[-1] != reference_date:
        raise RuntimeError("EXACT_40_SESSION_WINDOW_UNAVAILABLE")
    parts: list[pd.DataFrame] = []
    for day in dates:
        manifest = store.get_manifest("ETF", day)
        if not manifest or manifest["status"] != "COMPLETE":
            raise RuntimeError(f"KRX_ETF_RAW_PARTITION_NOT_COMPLETE:{day}")
        frame = store.load_snapshot("ETF", day)
        if frame["ticker"].duplicated().any():
            raise RuntimeError(f"DUPLICATE_TICKER_IN_KRX_ETF_RAW:{day}")
        parts.append(frame.loc[:, ["date", "ticker", "close", "volume", "trading_value", "market_cap"]])
    raw = pd.concat(parts, ignore_index=True)
    raw["date"] = pd.to_datetime(raw["date"]).dt.strftime("%Y-%m-%d")
    if raw.duplicated(["date", "ticker"]).any():
        raise RuntimeError("DUPLICATE_KRX_ETF_SESSION_TICKER")

    ranking = json.loads(ranking_path.read_text(encoding="utf-8"))
    metadata = {
        "reference_date": reference_date,
        "40D_start_date": dates[0], "40D_end_date": dates[-1],
        "40D_session_count": len(dates), "40D_session_dates": dates,
        "calendar_authority": calendar.source_name,
        "calendar_frontier": calendar.metadata.get("calendar_frontier"),
        "raw_endpoint": "KRX_OPEN_API_ETF_DAILY",
        "raw_partition_rows_by_date": {day: int(len(frame)) for day, frame in zip(dates, parts)},
        "ranking24_reference_date": ranking.get("reference_market_date"),
    }
    return reference_date, dates, raw, metadata


def build_universe(master_path: Path = DEFAULT_MASTER, ranking_path: Path = DEFAULT_RANKING, output_dir: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    root = ROOT
    output_dir.mkdir(parents=True, exist_ok=True)
    if str(root / "src") not in sys.path:
        sys.path.insert(0, str(root / "src"))
    master = pd.read_csv(master_path, dtype={"ISU_CD": "string", "ISU_SRT_CD": "string"}, encoding="utf-8-sig")
    required = {"ISU_CD", "ISU_SRT_CD", "ISU_NM", "ISU_ABBRV", "ISU_ENG_NM", "LIST_DD", "ETF_OBJ_IDX_NM", "ETF_REPLICA_METHD_TP_CD", "IDX_MKT_CLSS_NM", "IDX_ASST_CLSS_NM"}
    missing = sorted(required - set(master.columns))
    if missing or master.empty:
        raise ValueError(f"KRX_ETF_MASTER_INVALID:{missing}")
    master["ticker"] = master["ISU_SRT_CD"].astype(str).str.strip()
    if master["ticker"].duplicated().any():
        raise ValueError("DUPLICATE_TICKER_IN_CURRENT_KRX_ETF_MASTER")
    reference_date, session_dates, raw, market_meta = _load_market_rows(root, ranking_path=ranking_path)
    stored_hashes = master["source_sha256"].dropna().astype(str).unique().tolist() if "source_sha256" in master.columns else []
    source_hash = stored_hashes[0] if len(stored_hashes) == 1 else hashlib.sha256(master_path.read_bytes()).hexdigest()
    stored_snapshot_dates = master["snapshot_date"].dropna().astype(str).unique().tolist() if "snapshot_date" in master.columns else []
    snapshot_date = stored_snapshot_dates[0] if len(stored_snapshot_dates) == 1 else "2026-09-29"

    metrics: list[dict[str, Any]] = []
    session_set = set(session_dates)
    for ticker, group in raw.groupby("ticker", sort=False):
        if set(group["date"]) - session_set:
            raise RuntimeError("RAW_ROWS_OUTSIDE_40D_WINDOW")
        n = int(group["date"].nunique())
        latest = group.loc[group["date"].eq(reference_date)]
        latest_row = latest.iloc[0] if len(latest) == 1 else None
        exact_window = n == 40 and set(group["date"]) == session_set
        metrics.append({
            "ticker": str(ticker), "raw_session_count_40d": n,
            "reference_close": int(latest_row["close"]) if latest_row is not None else None,
            "avg_volume_40d": float(group["volume"].mean()) if exact_window else None,
            "avg_trading_value_40d": float(group["trading_value"].mean()) if exact_window else None,
            "AUM_if_available": int(latest_row["market_cap"]) if latest_row is not None and pd.notna(latest_row["market_cap"]) else None,
        })
    metric_frame = pd.DataFrame(metrics)
    classified_rows = [classify_product(row) for row in master.to_dict("records")]
    classified = pd.concat([master.reset_index(drop=True), pd.DataFrame(classified_rows)], axis=1)
    classified = classified.merge(metric_frame, on="ticker", how="left", validate="one_to_one")
    classified["listing_date"] = pd.to_datetime(classified["LIST_DD"], format="%Y/%m/%d", errors="coerce").dt.strftime("%Y-%m-%d")
    ref = pd.Timestamp(reference_date)
    classified["listing_age_days"] = (ref - pd.to_datetime(classified["listing_date"], errors="coerce")).dt.days
    classified["listing_age_years"] = classified["listing_age_days"] / 365.2425
    classified["snapshot_date"] = snapshot_date
    classified["product_master_source"] = SOURCE_NAME
    classified["product_master_sha256"] = source_hash

    classified["failed_filter"] = classified.apply(lambda row: hard_filter_failures(row, ref), axis=1).map("|".join)
    classified["hard_filter_pass"] = classified["failed_filter"].eq("")
    candidates = classified.loc[classified["hard_filter_pass"]].copy()
    selected = select_group_representatives(candidates)
    selected_tickers = set(selected["ticker"].astype(str))
    selected["was_in_existing_ranking_24"] = selected["ticker"].astype(str).isin(
        {str(item["ticker"]) for item in json.loads(ranking_path.read_text(encoding="utf-8"))["items"]}
    )
    selected["close"] = selected["reference_close"]
    selected["ETF_name"] = selected["ISU_ABBRV"]
    selected["tracking_quality_if_available"] = ""
    candidates = candidates.merge(selected.loc[:, ["ticker", "selection_reason"]], on="ticker", how="left")
    candidates["selected"] = candidates["ticker"].astype(str).isin(selected_tickers)
    candidates["reason"] = candidates["selection_reason"].fillna("")
    for idx, row in candidates.loc[~candidates["selected"]].iterrows():
        winner = selected.loc[
            selected["major_category"].eq(row["major_category"])
            & selected["representative_group"].eq(row["representative_group"]), "ticker"
        ]
        candidates.at[idx, "reason"] = f"LOWER_40D_AVERAGE_TRADING_VALUE_THAN:{winner.iloc[0]}" if len(winner) else "NO_GROUP_WINNER"
    ranking = json.loads(ranking_path.read_text(encoding="utf-8"))
    comparison = compare_ranking24(classified, selected, ranking)

    classified.to_csv(output_dir / "classified_universe.csv", index=False, encoding="utf-8-sig")
    snapshot = master.copy()
    snapshot["snapshot_date"] = snapshot_date
    snapshot["source_name"] = SOURCE_NAME
    snapshot["source_sha256"] = source_hash
    snapshot.to_csv(output_dir / "all_current_etf_snapshot.csv", index=False, encoding="utf-8-sig")
    candidate_columns = ["major_category", "representative_group", "ticker", "ISU_ABBRV", "listing_date", "listing_age_years", "reference_close", "avg_volume_40d", "avg_trading_value_40d", "AUM_if_available", "selected", "reason"]
    candidates.loc[:, candidate_columns].sort_values(["major_category", "representative_group", "avg_trading_value_40d"], ascending=[True, True, False], kind="mergesort").to_csv(output_dir / "eligible_candidates.csv", index=False, encoding="utf-8-sig")
    rep_columns = ["major_category", "representative_group", "ticker", "ETF_name", "listing_date", "listing_age_years", "close", "avg_volume_40d", "avg_trading_value_40d", "AUM_if_available", "tracking_quality_if_available", "selection_reason", "was_in_existing_ranking_24"]
    selected.loc[:, rep_columns].sort_values(["major_category", "representative_group"], kind="mergesort").to_csv(output_dir / "official_representative_etf_universe.csv", index=False, encoding="utf-8-sig")

    excluded = classified.loc[~classified["ticker"].astype(str).isin(selected_tickers)].copy()
    excluded["reason"] = excluded.apply(
        lambda row: row["failed_filter"] if row["failed_filter"] else "LOWER_40D_AVERAGE_TRADING_VALUE_WITHIN_GROUP",
        axis=1,
    )
    winner_by_group = {(r.major_category, r.representative_group): r.ticker for r in selected.itertuples(index=False)}
    excluded["selected_group_representative"] = excluded.apply(
        lambda row: winner_by_group.get((row["major_category"], row["representative_group"]), ""), axis=1
    )
    excluded.loc[:, ["ticker", "ISU_ABBRV", "major_category", "representative_group", "product_structure", "failed_filter", "reason", "selected_group_representative"]].to_csv(output_dir / "excluded_audit.csv", index=False, encoding="utf-8-sig")
    comparison.to_csv(output_dir / "comparison_vs_existing_ranking_24.csv", index=False, encoding="utf-8-sig")

    duplicate_tickers = int(classified["ticker"].duplicated().sum())
    duplicate_reps = int(selected["representative_group"].duplicated().sum())
    group_counts = selected.groupby(["major_category", "representative_group"]).size()
    validation = {
        "verdict": "ETF_OFFICIAL_UNIVERSE_REFINEMENT_V02_COMPLETE",
        "all_current_listed_etf_source_loaded": True,
        "snapshot_date": snapshot_date,
        "total_current_etf_count": int(len(master)),
        "source": SOURCE_NAME,
        "source_file_sha256": source_hash,
        "reference_date": reference_date,
        "40D_start_date": session_dates[0], "40D_end_date": session_dates[-1],
        "40D_session_count": len(session_dates),
        "40D_session_dates": session_dates,
        "raw_data_authority": "KRX_OPEN_API_ETF_DAILY",
        "calendar_authority": market_meta["calendar_authority"],
        "raw_partition_coverage_exact_40_sessions": len(market_meta["raw_partition_rows_by_date"]) == 40,
        "all_current_tickers_have_raw_rows_at_reference_date": int(classified["reference_close"].notna().sum()) == len(master),
        "duplicate_ticker_count": duplicate_tickers,
        "selected_hard_filter_violation_count": int((~selected["hard_filter_pass"]).sum()) if "hard_filter_pass" in selected else 0,
        "representative_duplicate_count": duplicate_reps,
        "representative_per_group_exactly_one": bool((group_counts == 1).all()),
        "unknown_selected_classification_count": int((~selected["major_category"].isin(["MARKET_INDEX", "SECTOR_INDEX", "COMMODITY_RESOURCE"])).sum()),
        "existing_ranking_24_used_as_source_universe": False,
        "existing_ranking_24_used_as_reference_only": True,
        "existing_ranking_24_count": len(ranking.get("items", [])),
        "ranking24_reference_date": market_meta["ranking24_reference_date"],
        "category_counts": {str(k): int(v) for k, v in classified["major_category"].value_counts().sort_index().items()},
        "eligible_candidate_count": int(len(candidates)),
        "selected_representative_count": int(len(selected)),
        "selected_by_category": {str(k): int(v) for k, v in selected["major_category"].value_counts().sort_index().items()},
        "hard_filter_thresholds": {
            "listing_age_min_years": 2,
            "avg_volume_40d_min_shares": 10000,
            "reference_close_min_krw": 1000,
            "avg_trading_value_40d_min_krw": 300000000,
            "required_product_structure": "PLAIN_LONG",
        },
        "selection_priority": ["avg_trading_value_40d", "AUM_if_available_within_1pct_turnover", "tracking_quality_if_available", "listing_age"],
        "commodity_spot_preferred": True,
        "ranking24_comparison_status_counts": {str(k): int(v) for k, v in comparison["comparison_status"].value_counts().sort_index().items()},
        "aum_source": "KRX ETF daily market_cap at reference_date; blank when unavailable",
        "tracking_quality": "Not available from the authorized local source; omitted as tie-breaker",
        "near_turnover_aum_tie_tolerance": NEAR_TURNOVER_RELATIVE_TOLERANCE,
        "source_detail": market_meta,
    }
    validation["passed"] = bool(
        validation["all_current_listed_etf_source_loaded"]
        and validation["total_current_etf_count"] == len(classified)
        and validation["duplicate_ticker_count"] == 0
        and validation["40D_session_count"] == 40
        and validation["raw_partition_coverage_exact_40_sessions"]
        and validation["selected_hard_filter_violation_count"] == 0
        and validation["representative_duplicate_count"] == 0
        and validation["representative_per_group_exactly_one"]
        and validation["unknown_selected_classification_count"] == 0
        and validation["existing_ranking_24_used_as_source_universe"] is False
        and validation["existing_ranking_24_used_as_reference_only"] is True
    )
    if not validation["passed"]:
        validation["verdict"] = "CHECK_REQUIRED"
    (output_dir / "validation.json").write_text(json.dumps(validation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# KRX current ETF representative universe refinement V02", "",
        f"- Verdict: **{validation['verdict']}**", f"- KRX ETF master snapshot: {snapshot_date} / {len(master):,} current ETF products", f"- Market reference date: {reference_date}",
        f"- Exact 40-session window: {session_dates[0]} through {session_dates[-1]} ({len(session_dates)} sessions)",
        f"- Source: {SOURCE_NAME}; liquidity and close: KRX_OPEN_API_ETF_DAILY", f"- Eligible candidates: {len(candidates):,}; selected representatives: {len(selected):,}",
        f"- Classification counts: `{json.dumps(validation['category_counts'], ensure_ascii=False, sort_keys=True)}`",
        "- Existing ETF Ranking 24: reference-only comparison; it did not constrain the search.",
        "- Near-tie rule: when top candidates' 40D mean turnover is within 1%, larger KRX reference-date market capitalization (AUM proxy) wins; listing age breaks an AUM tie.",
        "- Tracking quality: no authorized local measure available; omitted. AUM uses KRX reference-date market capitalization.", "",
        "## Scope and filters", "",
        "- Search universe: every product in the current KRX ETF product-master snapshot; ETNs and delisted products are outside that source.",
        "- Classifications: `MARKET_INDEX`, `SECTOR_INDEX`, `COMMODITY_RESOURCE`, or `OUT_OF_SCOPE`; only plain-long products in the first three categories can pass.",
        "- Hard filters as of the market reference date: listing age at least 2 years, reference close at least KRW 1,000, exact 40-session mean volume at least 10,000 shares, and exact 40-session mean trading value at least KRW 300 million.",
        "- All market metrics use exact KRX ETF raw sessions; no current metric is carried backward or forward-filled.",
        "- One representative per mapped exposure group. Highest 40D mean trading value wins except within the 1% near-tie band, where larger AUM proxy wins; spot commodities precede futures.",
        "- Out-of-scope includes fixed income/cash/rates, mixed assets, REITs, currency, leverage/inverse/short, option income, buffered payoffs, style/factor/dividend products, concentrated TOP-N and narrow themes/single-company mandates.", "",
        "## Selected representatives", "", "| Category | Group | Ticker | ETF | 40D mean trading value (KRW) | 40D mean volume | Ref close (KRW) | Existing Ranking 24 |", "|---|---|---:|---|---:|---:|---:|---|",
    ]
    for row in selected.sort_values(["major_category", "representative_group"]).itertuples(index=False):
        lines.append(f"| {row.major_category} | {row.representative_group} | {row.ticker} | {row.ETF_name} | {row.avg_trading_value_40d:,.0f} | {row.avg_volume_40d:,.0f} | {row.close:,.0f} | {'Yes' if row.was_in_existing_ranking_24 else 'No'} |")
    lines += ["", "## Ranking 24 comparison", "", "| Category | Group | Prior Ranking 24 tickers | Selected ticker | Status |", "|---|---|---|---|---|"]
    for row in comparison.itertuples(index=False):
        lines.append(f"| {row.major_category} | {row.representative_group} | {row.existing_ranking_24_tickers or '—'} | {row.selected_ticker or '—'} | {row.comparison_status} |")
    lines += ["", "## Validation", "", f"- All-current KRX ETF source loaded: `{validation['all_current_listed_etf_source_loaded']}`", f"- Duplicate ticker count: `{duplicate_tickers}`", f"- Exact 40-session count: `{len(session_dates)}`", f"- Selected hard-filter violations: `{validation['selected_hard_filter_violation_count']}`", f"- Duplicate representative groups: `{duplicate_reps}`", f"- Ranking 24 used as source universe: `False`", ""]
    (output_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    return validation


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--master", type=Path, default=DEFAULT_MASTER)
    parser.add_argument("--ranking", type=Path, default=DEFAULT_RANKING)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if args.master == DEFAULT_MASTER and not args.master.exists() and FALLBACK_MASTER.exists():
        args.master = FALLBACK_MASTER
    args.output.mkdir(parents=True, exist_ok=True)
    print(json.dumps(build_universe(args.master, args.ranking, args.output), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
