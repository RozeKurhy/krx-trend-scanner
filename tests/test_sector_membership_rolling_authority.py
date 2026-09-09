import csv
import json
from pathlib import Path

import pandas as pd
import pytest

from trend_scanner.data.krx_sector_index import KRX_NATIVE_SECTOR_INDEX_MAP
from trend_scanner.data.sector_membership import (
    STORE_COLUMNS,
    SectorMembershipSnapshotUnavailable,
    load_sector_membership_meta,
    load_sector_membership_snapshot,
    sector_membership_path_for_date,
)
from trend_scanner.data.sector_membership_rolling import (
    EXPECTED_SECTOR_COUNT,
    MARKETPLACE_ROOT,
    NATIVE_SECTOR_CODES,
    RollingMembershipError,
    SectorCheckpoint,
    build_rolling_sector_membership,
    collect_sector_checkpoints,
    load_marketplace_sector_checkpoints,
    resolve_sector_membership,
)


ROOT = Path(__file__).resolve().parents[1]


def _write_target(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "intervals": [
            {
                "ticker": row["ticker"],
                "market": row["market"],
                "state": "COMMON",
                "effective_from": "2026-01-01",
                "effective_to": "2026-12-31",
            }
            for row in rows
        ]
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_marketplace_fixture(
    root: Path,
    *,
    missing_code: str | None = None,
    sector_name_override: tuple[str, str] | None = None,
    rows_override: dict[str, list[dict[str, str]]] | None = None,
) -> None:
    raw_root = root / MARKETPLACE_ROOT / "20260904"
    manifest: list[dict[str, object]] = []
    rows_override = rows_override or {}
    for index, (code, contract) in enumerate(KRX_NATIVE_SECTOR_INDEX_MAP.items(), start=1):
        if code == missing_code:
            continue
        path = raw_root / code / "original" / "source.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        rows = rows_override.get(code, [{"종목코드": str(index).zfill(6), "종목명": "테스트종목"}])
        with path.open("w", encoding="cp949", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["종목코드", "종목명"])
            writer.writeheader()
            writer.writerows(rows)
        name = contract["idx_name"]
        if sector_name_override and sector_name_override[0] == code:
            name = sector_name_override[1]
        manifest.append(
            {
                "sector_code": code,
                "sector_name": name,
                "market": contract["market"],
                "effective_date": "2026-09-04",
                "file_path": str(path.relative_to(root)),
                "file_name": path.name,
                "encoding": "CP949",
                "row_count": len(rows),
                "ticker_column": "종목코드",
                "name_column": "종목명",
                "duplicate_ticker_count": 0,
                "blank_ticker_count": 0,
                "invalid_ticker_count": 0,
                "parse_status": "PASS",
            }
        )
    manifest_path = raw_root / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")


def _checkpoint(code: str, tickers: tuple[str, ...]) -> SectorCheckpoint:
    contract = KRX_NATIVE_SECTOR_INDEX_MAP[code]
    return SectorCheckpoint(
        sector_code=code,
        sector_name=contract["idx_name"],
        market=contract["market"],
        effective_date="2026-09-04",
        member_tickers=tickers,
        fetch_status="SUCCESS",
    )


def test_native_sector_contract_is_exactly_46_codes() -> None:
    assert len(NATIVE_SECTOR_CODES) == EXPECTED_SECTOR_COUNT == 46
    assert set(NATIVE_SECTOR_CODES) == set(KRX_NATIVE_SECTOR_INDEX_MAP)


def test_marketplace_loader_accepts_cp949_and_alphanumeric_tickers(tmp_path: Path) -> None:
    _write_marketplace_fixture(
        tmp_path,
        rows_override={"1005": [{"종목코드": "000001", "종목명": "테스트"}, {"종목코드": "0120G0", "종목명": "신규"}]},
    )
    checkpoints, report = load_marketplace_sector_checkpoints("2026-09-04", repo_root=tmp_path)
    assert len(checkpoints) == 46
    assert checkpoints[0].member_tickers == ("000001", "0120G0")
    assert report["successful_sector_count"] == 46
    assert report["source_method"] == "KRX_DATA_MARKETPLACE_OFFICIAL_INDEX_CONSTITUENTS_CSV"


def test_marketplace_loader_rejects_missing_sector(tmp_path: Path) -> None:
    _write_marketplace_fixture(tmp_path, missing_code="1005")
    with pytest.raises(RollingMembershipError, match="SECTOR_CONTRACT_MISMATCH"):
        load_marketplace_sector_checkpoints("2026-09-04", repo_root=tmp_path)


def test_marketplace_loader_rejects_duplicate_ticker(tmp_path: Path) -> None:
    _write_marketplace_fixture(
        tmp_path,
        rows_override={"1005": [{"종목코드": "000001", "종목명": "가"}, {"종목코드": "000001", "종목명": "나"}]},
    )
    with pytest.raises(RollingMembershipError, match="DUPLICATE_TICKER"):
        load_marketplace_sector_checkpoints("2026-09-04", repo_root=tmp_path)


@pytest.mark.parametrize(
    ("row", "error"),
    [
        ({"종목코드": "", "종목명": "빈코드"}, "BLANK_TICKER"),
        ({"종목코드": "BAD!", "종목명": "잘못된코드"}, "INVALID_TICKER_PAYLOAD"),
    ],
)
def test_marketplace_loader_rejects_blank_or_invalid_ticker(
    tmp_path: Path,
    row: dict[str, str],
    error: str,
) -> None:
    _write_marketplace_fixture(tmp_path, rows_override={"1005": [row]})
    with pytest.raises(RollingMembershipError, match=error):
        load_marketplace_sector_checkpoints("2026-09-04", repo_root=tmp_path)


def test_marketplace_loader_rejects_sector_name_mismatch(tmp_path: Path) -> None:
    _write_marketplace_fixture(tmp_path, sector_name_override=("1005", "잘못된 이름"))
    with pytest.raises(RollingMembershipError, match="CONTRACT_MISMATCH"):
        load_marketplace_sector_checkpoints("2026-09-04", repo_root=tmp_path)


def test_legacy_and_rolling_snapshot_loaders_are_exact_date_selected(tmp_path: Path) -> None:
    legacy = load_sector_membership_snapshot("2026-08-14", repo_root=ROOT)
    assert len(legacy) == 2528
    assert set(legacy["effective_date"]) == {"2026-08-14"}

    rolling = pd.DataFrame(
        [["000001", "KOSPI", "2026-09-04", "1005", "음식료·담배", "MAPPED", "MOST_SPECIFIC_NATIVE_SECTOR_V01", "TEST", "sha"]],
        columns=list(STORE_COLUMNS),
    )
    rolling_path = sector_membership_path_for_date("2026-09-04", tmp_path)
    rolling_path.parent.mkdir(parents=True, exist_ok=True)
    rolling.to_parquet(rolling_path, index=False)
    loaded = load_sector_membership_snapshot("2026-09-04", repo_root=tmp_path)
    assert loaded["ticker"].tolist() == ["000001"]
    with pytest.raises(SectorMembershipSnapshotUnavailable):
        load_sector_membership_snapshot("2026-09-05", repo_root=tmp_path)


def test_real_marketplace_snapshot_and_production_store_are_exact_date_validated() -> None:
    checkpoints, report = load_marketplace_sector_checkpoints("2026-09-04", repo_root=ROOT)
    assert len(checkpoints) == 46
    assert report["successful_sector_count"] == 46

    snapshot = load_sector_membership_snapshot("2026-09-04", repo_root=ROOT)
    meta = load_sector_membership_meta("2026-09-04", repo_root=ROOT)
    assert len(snapshot) == 2562
    assert meta["snapshot_effective_date"] == "2026-09-04"
    assert meta["sector_count"] == 46
    assert meta["target_population"] == 2562
    assert meta["mapped_count"] == 2440
    assert meta["aggregate_only_count"] == 88
    assert meta["unmapped_count"] == 34
    with pytest.raises(SectorMembershipSnapshotUnavailable):
        load_sector_membership_snapshot("2026-09-05", repo_root=ROOT)


def test_specific_leaf_wins_aggregate_and_missing_is_fail_closed() -> None:
    target = pd.DataFrame(
        [["000001", "KOSPI"], ["000002", "KOSPI"], ["000003", "KOSPI"], ["000004", "KOSPI"]],
        columns=["ticker", "market"],
    )
    checkpoints = (
        _checkpoint("1009", ("000001",)),
        _checkpoint("1027", ("000001", "000002")),
        _checkpoint("1021", ("000004",)),
        _checkpoint("1025", ("000004",)),
    )
    result = resolve_sector_membership(target, checkpoints, effective_date="2026-09-04")
    by_ticker = result.set_index("ticker")
    assert (by_ticker.loc["000001", "sector_code"], by_ticker.loc["000001", "resolution_status"]) == ("1009", "MAPPED")
    assert (by_ticker.loc["000002", "sector_code"], by_ticker.loc["000002", "resolution_status"]) == ("1027", "AGGREGATE_ONLY")
    assert (by_ticker.loc["000003", "resolution_status"]) == "UNMAPPED"
    assert (by_ticker.loc["000004", "sector_code"]) == "1025"


def test_duplicate_final_ticker_rejected() -> None:
    target = pd.DataFrame([["000001", "KOSPI"], ["000001", "KOSPI"]], columns=["ticker", "market"])
    with pytest.raises(RollingMembershipError, match="DUPLICATE_FINAL_TICKER"):
        resolve_sector_membership(target, (_checkpoint("1005", ("000001",)),), effective_date="2026-09-04")


def test_failed_partial_run_does_not_publish(tmp_path: Path) -> None:
    target_path = tmp_path / "target.json"
    _write_target(target_path, [{"ticker": "000001", "market": "KOSPI"}])
    calls: list[str] = []

    def fail_fetch(code: str, request_date: str) -> list[str]:
        calls.append(code)
        raise RuntimeError("blocked")

    result = build_rolling_sector_membership(
        repo_root=tmp_path,
        target_universe_path=target_path,
        fetcher=fail_fetch,
        sleep_fn=lambda _: None,
        min_inter_call_seconds=10,
    )
    assert calls == [NATIVE_SECTOR_CODES[0]]
    assert result.report["published"] is False
    assert not sector_membership_path_for_date("2026-09-04", tmp_path).exists()


def test_45_of_46_successful_sectors_does_not_publish(tmp_path: Path) -> None:
    target_path = tmp_path / "target.json"
    _write_target(target_path, [{"ticker": "000001", "market": "KOSPI"}])
    calls: list[str] = []

    def fail_on_last(code: str, request_date: str) -> list[str]:
        calls.append(code)
        if len(calls) == 46:
            raise RuntimeError("blocked")
        return ["000001"]

    result = build_rolling_sector_membership(
        repo_root=tmp_path,
        target_universe_path=target_path,
        fetcher=fail_on_last,
        sleep_fn=lambda _: None,
        min_inter_call_seconds=10,
    )
    assert len(calls) == 46
    assert result.report["successful_sector_count"] == 45
    assert result.report["published"] is False
    assert not sector_membership_path_for_date("2026-09-04", tmp_path).exists()


def test_checkpoint_reuse_makes_second_run_network_free(tmp_path: Path) -> None:
    target_path = tmp_path / "target.json"
    rows = [
        {"ticker": str(index).zfill(6), "market": "KOSPI" if index <= 24 else "KOSDAQ"}
        for index in range(1, 47)
    ]
    _write_target(target_path, rows)
    calls: list[str] = []

    def fetch(code: str, request_date: str) -> list[str]:
        calls.append(code)
        return [str(len(calls)).zfill(6)]

    first = build_rolling_sector_membership(
        repo_root=tmp_path,
        target_universe_path=target_path,
        fetcher=fetch,
        sleep_fn=lambda _: None,
        min_inter_call_seconds=10,
    )
    assert first.report["published"] is True
    assert first.report["target_reconciliation"] is True
    calls.clear()
    second = build_rolling_sector_membership(
        repo_root=tmp_path,
        target_universe_path=target_path,
        fetcher=fetch,
        sleep_fn=lambda _: None,
        min_inter_call_seconds=10,
    )
    assert calls == []
    assert second.report["attempted_calls"] == 0
    assert second.report["cache_hits"] == 46
    assert second.report["published"] is False


def test_collection_enforces_10_second_delay_and_46_call_cap(tmp_path: Path) -> None:
    sleep_calls: list[float] = []
    calls: list[str] = []

    def fetch(code: str, request_date: str) -> list[str]:
        calls.append(code)
        return [str(len(calls)).zfill(6)]

    checkpoints, report = collect_sector_checkpoints(
        "2026-09-04",
        repo_root=tmp_path,
        fetcher=fetch,
        sleep_fn=sleep_calls.append,
        monotonic_fn=lambda: 0.0,
        min_inter_call_seconds=10,
    )
    assert len(checkpoints) == 46
    assert len(calls) == 46
    assert report["attempted_calls"] == 46
    assert report["duplicate_calls"] == 0
    assert sleep_calls == [10.0] * 45
