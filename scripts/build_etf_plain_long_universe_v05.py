#!/usr/bin/env python3
"""Build the conservative V05 plain-long ETF universe from KRX product metadata."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "artifacts/research/etf_plain_long_market_sector_resource_v05/krx_etf_product_metadata_2026-09-29.csv"
DEFAULT_OUTPUT = ROOT / "artifacts/research/etf_plain_long_market_sector_resource_v05"
TARGET_CATEGORIES = {"MARKET_INDEX", "SECTOR_INDUSTRY", "COMMODITY_RESOURCE"}

# Classify from KRX's current asset class and official objective-index name.
# Product-name terms are only used for explicit exclusions (e.g. inverse,
# covered call) or when the KRX objective itself does not identify an industry.
_DIRECTIONAL = re.compile(
    r"레버리지|인버스|inverse|leverag|\b1\.5\s*x\b|\b2\s*x\b|\b3\s*x\b|\b2x\b|\b3x\b|2배|3배|롱.{0,12}숏|\bshort\b|\bbear\b",
    re.IGNORECASE,
)
_OPTION_INCOME = re.compile(
    r"커버드.?콜|covered.?call|buy\s*write|buywrite|콜매도|옵션.?프리미엄|option.?premium|인컴|income",
    re.IGNORECASE,
)
_BUFFERED = re.compile(r"buffer|버퍼|defined\s*outcome|목표헤지", re.IGNORECASE)
_FIXED_INCOME = re.compile(
    r"채권|국채|회사채|단기채|초단기|머니마켓|KOFR|\bCD\b|CD금리|SOFR|금리|TDF|target.?date|treasury|\bbond\b|money.?market",
    re.IGNORECASE,
)
_HIGH_DIVIDEND = re.compile(
    r"고배당|고배당주|배당주|배당|dividend",
    re.IGNORECASE,
)
_STYLE = re.compile(
    r"밸류업|value.?up|가치주|성장주|그로스|성장기업|성장액티브|large.?cap.?value|large.?cap.?growth|(?:value|growth)\s*(?:index|지수)|ESG|기후변화|기후.?솔루션|carbon|탄소|저변동|최소변동|low.?vol|quality|퀄리티|동일가중|equal.?weight|모멘텀|momentum|주주환원|주주가치|자사주|고정배당|고정피지컬AI|고정테크|하이베타|high.?beta|멀티팩터|multi.?factor|블루칩|blue.?chip|고정테크|혁신기술|innovation|글로벌플랫폼|global.?platform|글로벌대장장이|영에이지|young.?age|다이나믹.?시니어|dynamic.?senior|R.?&.?D|베스트.?일레븐|best.?eleven|중소형.?포커스|중소형포커스",
    re.IGNORECASE,
)
_CONCENTRATED_BROAD = re.compile(
    r"\btop\s*(?:2|3|4|5|7|10|20|30)\b|focus\s*\d+|포커스\s*\d+|top\d+|중소형|중형주|소형주|mid.?cap|small.?cap|ex.?top|우선주|preferred|next.?generation|일등기업|글로벌대장|global.?leader|글로벌영에이지|글로벌다이나믹시니어|베스트.?일레븐|best.?eleven",
    re.IGNORECASE,
)
_SINGLE_STOCK_INDEX = re.compile(
    r"KRX\s*(?:삼성전자|SK하이닉스|현대차|테슬라|엔비디아)\s*(?:선물\s*)?지수",
    re.IGNORECASE,
)
_NARROW_ACTIVE_MANDATE = re.compile(r"AI.?코리아|코리아.?AI|AI.?Korea|Korea.?AI", re.IGNORECASE)
_COMPOSITE = re.compile(
    r"\bblend\b|\bblended\b|혼합지수|\b50\s*/\s*50\b|\b90\s*/\s*10\b|\b70\s*/\s*30\b|\b30\s*/\s*70\b|&\s*(?:S&P|gold|금|채권)|(?:S&P|gold|금)\s*&",
    re.IGNORECASE,
)

_MARKET_INDEX = re.compile(
    r"코스피\s*(?:200|100|50|대형주|중형주|중소형주|TR)?|"
    r"코스닥\s*(?:150|글로벌|TR)?|KRX\s*(?:300|100|200)|KTOP\s*30|"
    r"KOSPI\s*(?:200|100|50)?|KOSDAQ\s*(?:150|GLOBAL)?|"
    r"S\s*&\s*P\s*(?:500|400|100|Korea|Asia\s*50|Global\s*1200)|S&P\s*(?:500|400|100|Korea|Asia\s*50|Global\s*1200)|"
    r"NASDAQ\s*(?:100|COMPOSITE|NEXT\s*GENERATION\s*100)|"
    r"MSCI\s*(?:WORLD|ACWI|EM(?:\s|$)|EMERGING|EAFE|KOREA|CHINA|INDIA|JAPAN|TAIWAN|USA|US\b|EUROPE|MEXICO|VIETNAM|BRAZIL|INDONESIA|THAILAND|MALAYSIA|SINGAPORE|TURKEY|GERMANY|FRANCE|AUSTRALIA|PHILIPPINES|RUSSIA|CANADA)|"
    r"DOW\s*JONES\s*(?:INDUSTRIAL|U\.S\. LARGE.?CAP)|DJIA|"
    r"TOPIX|NIKKEI\s*225|EURO\s*STOXX\s*50|STOXX\s*EUROPE\s*600|"
    r"FTSE\s*(?:100|ALL.?WORLD|EMERGING|CHINA|EAFE)|NIFTY\s*(?:50|MIDCAP\s*100)|"
    r"CSI\s*(?:300|500|1000|A\s*50|A\s*100)|CSI\s*A\s*(?:50|100)|"
    r"HANG\s*SENG(?!.*TECH)|TAIWAN\s*WEIGHTED|TAIEX|DAX\s*40|CAC\s*40|"
    r"IBOVESPA|VN\s*30|VN30|SZSE\s*CHINEXT|CHINEXT|NYSE\s*100|"
    r"RUSSELL\s*(?:1000|2000|3000)|FTSE\s*GLOBAL\s*ALL\s*CAP",
    re.IGNORECASE,
)

_SECTOR = re.compile(
    r"반도체|semi.?conductor|memory|메모리|2차전지|배터리|battery|전기차|electric\s*vehicle|"
    r"자동차|mobility|조선|shipbuilding|방산|방위산업|defen[cs]e|aerospace|우주|위성통신|"
    r"바이오|헬스케어|health.?care|제약|pharma|의료기기|의료|금융|은행|보험|증권|financial|banking|"
    r"\bIT\b|정보기술|technology|\btech\b|software|소프트웨어|클라우드|data\s*cent(er|re)|데이터센터|"
    r"robot|로봇|quantum\s*computing|양자컴퓨팅|화학|chemical|철강|steel|에너지|energy|oil\s*&\s*gas|"
    r"oil\s+and\s+gas|원유생산|전력|원자력|원전|수소|hydrogen|신재생|풍력|태양광|solar|"
    r"미디어|콘텐츠|엔터|게임|gaming|소비재|consumer\s*(?:staples|discretionary)|유통|화장품|건설|construction|"
    r"산업재|industrial|전기\s*기기|전력기기|리튬|니켈|석유화학|철도|항공|여행|호텔|통신|communications|"
    r"인터넷|internet|e.?commerce|e커머스|웹툰|드라마|게임|food\s*&\s*beverage|식품|제조업|manufacturing|"
    r"반려동물|농업융복합산업|global\s*luxury|럭셔리|infrastructure|인프라",
    re.IGNORECASE,
)

_COMMODITY = re.compile(
    r"금|gold|은|silver|원유|crude|\bWTI\b|구리|copper|콩|soybean|농산물|농산|곡물|grains|"
    r"팔라듐|palladium|백금|platinum|천연가스|natural\s*gas|commodity|resource",
    re.IGNORECASE,
)


def _combined_text(row: dict[str, Any]) -> str:
    return " ".join(str(row.get(field, "")) for field in (
        "ISU_NM", "ISU_ABBRV", "ISU_ENG_NM", "ETF_OBJ_IDX_NM",
        "ETF_REPLICA_METHD_TP_CD",
    ))


def classify_product(row: dict[str, Any]) -> dict[str, Any]:
    ticker = str(row.get("ISU_SRT_CD", "")).strip().zfill(6)
    name = str(row.get("ISU_ABBRV", "")).strip()
    objective = str(row.get("ETF_OBJ_IDX_NM", "")).strip()
    asset = str(row.get("IDX_ASST_CLSS_NM", "")).strip()
    listing = pd.to_datetime(str(row.get("LIST_DD", "")), errors="coerce")
    text = _combined_text(row)

    if asset == "원자재" and _COMMODITY.search(text):
        category = "COMMODITY_RESOURCE"
        basis = f"KRX IDX_ASST_CLSS_NM=원자재; ETF_OBJ_IDX_NM={objective}"
    elif asset == "주식" and _SECTOR.search(objective):
        category = "SECTOR_INDUSTRY"
        basis = f"KRX IDX_ASST_CLSS_NM=주식; ETF_OBJ_IDX_NM={objective} identifies an industry/sector"
    elif asset == "주식" and _MARKET_INDEX.search(objective):
        category = "MARKET_INDEX"
        basis = f"KRX IDX_ASST_CLSS_NM=주식; ETF_OBJ_IDX_NM={objective} identifies a broad market/country index"
    elif asset == "채권":
        category = "FIXED_INCOME_RATE_CASH_EXCLUDED"
        basis = f"KRX IDX_ASST_CLSS_NM=채권; ETF_OBJ_IDX_NM={objective}"
    elif asset == "혼합자산":
        category = "MIXED_ASSET_EXCLUDED"
        basis = f"KRX IDX_ASST_CLSS_NM=혼합자산; ETF_OBJ_IDX_NM={objective}"
    elif asset == "통화":
        category = "CURRENCY_EXCLUDED"
        basis = f"KRX IDX_ASST_CLSS_NM=통화; ETF_OBJ_IDX_NM={objective}"
    elif asset == "부동산":
        category = "PROPERTY_REIT_EXCLUDED"
        basis = f"KRX IDX_ASST_CLSS_NM=부동산; ETF_OBJ_IDX_NM={objective}"
    elif asset == "기타":
        category = "OTHER_ASSET_CLASS_EXCLUDED"
        basis = f"KRX IDX_ASST_CLSS_NM=기타; ETF_OBJ_IDX_NM={objective}"
    else:
        category = "UNCLASSIFIED_EXCLUDED"
        basis = f"KRX IDX_ASST_CLSS_NM={asset}; ETF_OBJ_IDX_NM={objective}"

    plain_long = not bool(_DIRECTIONAL.search(text) or _OPTION_INCOME.search(text) or _BUFFERED.search(text) or _COMPOSITE.search(text))
    reason = ""
    if not plain_long:
        if _DIRECTIONAL.search(text):
            reason = "LEVERAGE_INVERSE_OR_SHORT"
        elif _OPTION_INCOME.search(text):
            reason = "COVERED_CALL_OR_OPTION_INCOME"
        elif _BUFFERED.search(text):
            reason = "BUFFERED_OR_DEFINED_OUTCOME"
        else:
            reason = "MIXED_OR_COMPOSITE_PAYOFF"
    elif asset == "채권" or (asset == "기타" and _FIXED_INCOME.search(text)):
        reason = "FIXED_INCOME_RATE_OR_CASH"
    elif asset == "혼합자산" or _FIXED_INCOME.search(text):
        plain_long = False
        reason = "MIXED_ASSET_OR_FIXED_INCOME"
    elif asset == "통화":
        reason = "CURRENCY_EXCLUDED"
    elif asset == "부동산" or re.search(r"리츠|\bREIT\b|real\s*estate", text, re.IGNORECASE):
        reason = "PROPERTY_OR_REIT_EXCLUDED"
    elif asset == "기타":
        reason = "OTHER_ASSET_CLASS_EXCLUDED"
    elif _HIGH_DIVIDEND.search(text):
        reason = "HIGH_DIVIDEND_OR_INCOME_STYLE"
    elif _STYLE.search(text):
        reason = "STYLE_OR_COMPOSITE_INDEX_OUTSIDE_TARGET"
    elif category == "MARKET_INDEX" and _NARROW_ACTIVE_MANDATE.search(name):
        category = "UNCLASSIFIED_EXCLUDED"
        reason = "NARROW_ACTIVE_MANDATE_WITH_BROAD_REFERENCE_INDEX"
    elif category == "MARKET_INDEX" and _CONCENTRATED_BROAD.search(text):
        category = "UNCLASSIFIED_EXCLUDED"
        reason = "CONCENTRATED_OR_NON_BROAD_MARKET_INDEX"
    elif category == "MARKET_INDEX" and _BUFFERED.search(text):
        category = "UNCLASSIFIED_EXCLUDED"
        reason = "BUFFERED_OR_DEFINED_OUTCOME"
    elif _SINGLE_STOCK_INDEX.search(objective):
        category = "UNCLASSIFIED_EXCLUDED"
        reason = "SINGLE_STOCK_UNDERLYING"
    elif category == "UNCLASSIFIED_EXCLUDED":
        reason = "AMBIGUOUS_OR_OUTSIDE_TARGET_CATEGORIES"

    include = category in TARGET_CATEGORIES and plain_long and not reason
    if not include and not reason:
        reason = "NOT_A_CLEAR_TARGET_CATEGORY"
    return {
        "ticker": ticker,
        "ISU_CD": str(row.get("ISU_CD", "")).strip(),
        "ETF_name": name,
        "listing_date": listing.strftime("%Y-%m-%d") if not pd.isna(listing) else "",
        "category": category,
        "classification_basis": basis,
        "plain_long": bool(plain_long),
        "include": bool(include),
        "exclude_reason": "" if include else reason,
        "official_objective_index": objective,
        "official_asset_class": asset,
        "official_market_class": str(row.get("IDX_MKT_CLSS_NM", "")).strip(),
        "official_replication_method": str(row.get("ETF_REPLICA_METHD_TP_CD", "")).strip(),
    }


def build_universe(source_path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    official = pd.read_csv(source_path, dtype={"ISU_CD": "string", "ISU_SRT_CD": "string"}, encoding="utf-8-sig")
    required = {"ISU_CD", "ISU_SRT_CD", "ISU_NM", "ISU_ABBRV", "ISU_ENG_NM", "LIST_DD", "ETF_OBJ_IDX_NM", "ETF_REPLICA_METHD_TP_CD", "IDX_MKT_CLSS_NM", "IDX_ASST_CLSS_NM"}
    missing = sorted(required - set(official.columns))
    if missing:
        raise ValueError(f"KRX_ETF_MASTER_REQUIRED_FIELDS_MISSING:{missing}")
    if official.empty or official["ISU_SRT_CD"].astype(str).duplicated().any():
        raise ValueError("KRX_ETF_MASTER_EMPTY_OR_DUPLICATE_TICKER")
    if official[["ISU_CD", "ISU_ABBRV", "LIST_DD", "ETF_OBJ_IDX_NM", "IDX_ASST_CLSS_NM"]].isna().any().any():
        raise ValueError("KRX_ETF_MASTER_REQUIRED_VALUE_MISSING")
    records = [classify_product(row) for row in official.to_dict("records")]
    classified = pd.DataFrame(records).sort_values("ticker").reset_index(drop=True)
    included = classified[classified["include"]].copy()
    source_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
    summary = {
        "snapshot_date": "2026-09-29",
        "source_name": "KRX MDC ETF_전종목기본종목",
        "source_path": str(source_path),
        "source_file_sha256": source_hash,
        "current_etf_count": int(len(official)),
        "plain_long_included_count": int(len(included)),
        "included_category_counts": {str(k): int(v) for k, v in included["category"].value_counts().sort_index().items()},
        "excluded_reason_counts": {str(k): int(v) for k, v in classified.loc[~classified["include"], "exclude_reason"].value_counts().sort_index().items()},
        "ambiguous_excluded_count": int((classified["category"] == "UNCLASSIFIED_EXCLUDED").sum()),
        "all_current_etfs_classified": bool(len(classified) == len(official) and classified["ticker"].nunique() == len(official)),
    }
    return classified, summary


def _write_review(output_dir: Path, classified: pd.DataFrame, summary: dict[str, Any]) -> None:
    included = classified[classified["include"]]
    ambiguous = classified[classified["category"] == "UNCLASSIFIED_EXCLUDED"]
    lines = [
        "# V05 KRX ETF universe classification review", "",
        f"- Current KRX ETF product-master rows: {summary['current_etf_count']:,}",
        f"- Included plain-long target ETFs: {summary['plain_long_included_count']:,}",
        f"- Included by category: `{json.dumps(summary['included_category_counts'], ensure_ascii=False)}`",
        f"- Ambiguous/out-of-scope products kept excluded: {len(ambiguous):,}", "",
        "## Exclusion reason counts", "",
        "| reason | count |", "|---|---:|",
    ]
    for reason, count in sorted(summary["excluded_reason_counts"].items()):
        lines.append(f"| {reason} | {count:,} |")
    lines += [
        "",
        "## Included ETF list", "",
        "| ticker | ETF name | category | KRX official classification basis |", "|---|---|---|---|",
    ]
    for row in included.itertuples(index=False):
        basis = str(row.classification_basis).replace("|", "\\|")
        lines.append(f"| {row.ticker} | {row.ETF_name} | {row.category} | {basis} |")
    lines += ["", "## Ambiguous or out-of-scope stock ETF list", "", "| ticker | ETF name | KRX objective index | reason |", "|---|---|---|---|"]
    for row in ambiguous.itertuples(index=False):
        idx = str(row.official_objective_index).replace("|", "\\|")
        lines.append(f"| {row.ticker} | {row.ETF_name} | {idx} | {row.exclude_reason} |")
    lines.append("")
    (output_dir / "universe_classification_review.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    classified, summary = build_universe(args.input)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    classified.to_csv(args.output_dir / "universe_classification_2026-09-29.csv", index=False, encoding="utf-8-sig")
    classified[classified["include"]].to_csv(args.output_dir / "included_plain_long_universe_2026-09-29.csv", index=False, encoding="utf-8-sig")
    classified[classified["category"] == "UNCLASSIFIED_EXCLUDED"].to_csv(args.output_dir / "ambiguous_excluded_2026-09-29.csv", index=False, encoding="utf-8-sig")
    _write_review(args.output_dir, classified, summary)
    summary["classification_file_sha256"] = hashlib.sha256((args.output_dir / "universe_classification_2026-09-29.csv").read_bytes()).hexdigest()
    summary["included_file_sha256"] = hashlib.sha256((args.output_dir / "included_plain_long_universe_2026-09-29.csv").read_bytes()).hexdigest()
    (args.output_dir / "universe_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
