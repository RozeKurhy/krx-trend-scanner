"""Phase 3G orchestration for one-target analysis-input updates.

This module sequences the existing Phase 3A--3F entrypoints.  It owns only
one shared ``target_as_of``, dependency gating, and the five-input status
composition contract; it does not duplicate any data collection or ranking
logic.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
import importlib.util
import inspect
import json
from pathlib import Path
import sys
from types import ModuleType
from typing import Any, Callable, Mapping

import pandas as pd

from trend_scanner.data.foreign_flow_rolling import update_foreign_flow_snapshot
from trend_scanner.data.market_calendar import (
    load_rolling_production_market_calendar,
    resolve_reference_market_date,
)
from trend_scanner.data.rolling_market_data_refresh import (
    DEFAULT_ROLLING_AUTHORITY_DIR,
    load_rolling_authority,
)
from trend_scanner.data.sector_index_rolling import update_sector_index_rolling
from trend_scanner.data.sector_membership import (
    SectorMembershipSnapshotUnavailable,
    resolve_sector_membership_snapshot_for_target,
)
from trend_scanner.data.sector_membership_rolling import (
    RollingMembershipError,
    load_local_target_universe,
)
from trend_scanner.universe.instrument_metadata import load_target_production_universe


PASS = "PASS"
NOOP_ALREADY_COMPLETE = "NOOP_ALREADY_COMPLETE"
BLOCKED = "BLOCKED"
FAILED = "FAILED"
STEP_STATUSES = frozenset({PASS, NOOP_ALREADY_COMPLETE, BLOCKED, FAILED})
TOP_LEVEL_STEPS = (
    "foreign_flow",
    "fundamentals",
    "market_rs",
    "sector_membership",
    "sector_rs",
)
ROOT = Path(__file__).resolve().parents[3]


class Phase3BlockedError(RuntimeError):
    """Expected Phase 3 input or dependency block."""


@dataclass(frozen=True)
class Phase3StepResult:
    """One normalized Phase 3 top-level or nested execution result."""

    status: str
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, **self.details}


@dataclass(frozen=True)
class Phase3RunResult:
    """Structured result of the five-input Phase 3 coordination contract."""

    target_as_of: str
    reference_market_date: str | None
    overall_status: str
    steps: dict[str, Phase3StepResult]

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_as_of": self.target_as_of,
            "requested_as_of": self.target_as_of,
            "reference_market_date": self.reference_market_date,
            "overall_status": self.overall_status,
            "steps": {name: result.to_dict() for name, result in self.steps.items()},
        }


StepRunner = Callable[..., Mapping[str, Any] | Phase3StepResult | Any]
ReferenceDateResolver = Callable[[str], str]


def normalize_target_as_of(value: str) -> str:
    """Validate the sole target date without consulting system time."""

    try:
        normalized = pd.Timestamp(str(value)).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("INVALID_TARGET_AS_OF") from exc
    if normalized != str(value):
        raise ValueError("INVALID_TARGET_AS_OF")
    return normalized


def compose_phase3_status(statuses: Mapping[str, str]) -> str:
    """Compose exactly five Phase 3 top-level statuses by contract priority."""

    if len(statuses) != len(TOP_LEVEL_STEPS) or set(statuses) != set(TOP_LEVEL_STEPS):
        raise ValueError("PHASE3_TOP_LEVEL_STEP_SET_INVALID")
    values = tuple(str(statuses[name]).upper() for name in TOP_LEVEL_STEPS)
    if any(status not in STEP_STATUSES for status in values):
        raise ValueError("PHASE3_STATUS_INVALID")
    if FAILED in values:
        return FAILED
    if BLOCKED in values:
        return BLOCKED
    if all(status == NOOP_ALREADY_COMPLETE for status in values):
        return NOOP_ALREADY_COMPLETE
    return PASS


def _compose_dependency_status(*statuses: str) -> str:
    """Apply the same priority to one internal dependency chain."""

    values = tuple(str(status).upper() for status in statuses)
    if any(status not in STEP_STATUSES for status in values):
        raise ValueError("PHASE3_STATUS_INVALID")
    if FAILED in values:
        return FAILED
    if BLOCKED in values:
        return BLOCKED
    if all(status == NOOP_ALREADY_COMPLETE for status in values):
        return NOOP_ALREADY_COMPLETE
    return PASS


def _result_mapping(value: Mapping[str, Any] | Phase3StepResult | Any) -> dict[str, Any]:
    if isinstance(value, Phase3StepResult):
        return value.to_dict()
    if isinstance(value, Mapping):
        return dict(value)
    method = getattr(value, "to_dict", None)
    if callable(method):
        mapped = method()
        if isinstance(mapped, Mapping):
            return dict(mapped)
    if is_dataclass(value):
        return asdict(value)
    raise ValueError("PHASE3_STEP_RESULT_UNSTRUCTURED")


def _normalize_step_result(
    value: Mapping[str, Any] | Phase3StepResult | Any,
    target_as_of: str,
    reference_market_date: str | None = None,
) -> Phase3StepResult:
    mapped = _result_mapping(value)
    status = str(mapped.pop("status", "")).upper()
    if status not in STEP_STATUSES:
        raise ValueError("PHASE3_STEP_STATUS_INVALID")
    reported_target = mapped.get("target_as_of", mapped.get("requested_as_of"))
    if reported_target is not None and str(reported_target) != target_as_of:
        raise ValueError("PHASE3_STEP_TARGET_AS_OF_MISMATCH")
    reported_reference = mapped.get("reference_market_date")
    if (
        reference_market_date is not None
        and reported_reference is not None
        and str(reported_reference) != reference_market_date
    ):
        raise ValueError("PHASE3_STEP_REFERENCE_MARKET_DATE_MISMATCH")
    return Phase3StepResult(status=status, details=mapped)


def _exception_result(exc: Exception) -> Phase3StepResult:
    if isinstance(exc, (Phase3BlockedError, SectorMembershipSnapshotUnavailable, RollingMembershipError)):
        return Phase3StepResult(BLOCKED, {"reason": str(exc) or type(exc).__name__})
    return Phase3StepResult(FAILED, {"reason": f"UNEXPECTED_{type(exc).__name__}"})


def _run_step(
    runner: StepRunner,
    target_as_of: str,
    reference_market_date: str | None = None,
) -> Phase3StepResult:
    try:
        parameters = inspect.signature(runner).parameters.values()
        accepts_reference = any(
            parameter.name == "reference_market_date"
            or parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in parameters
        )
        value = (
            runner(target_as_of, reference_market_date=reference_market_date)
            if accepts_reference
            else runner(target_as_of)
        )
        return _normalize_step_result(value, target_as_of, reference_market_date)
    except Exception as exc:  # noqa: BLE001 - normalized at the orchestration boundary
        return _exception_result(exc)


class Phase3Coordinator:
    """Coordinate existing 3A--3F entrypoints without reimplementing them."""

    def __init__(
        self,
        *,
        foreign_flow: StepRunner,
        fundamentals: StepRunner,
        market_rs: StepRunner,
        sector_membership: StepRunner,
        sector_index: StepRunner,
        sector_rs_ranking: StepRunner,
        reference_market_date_resolver: ReferenceDateResolver | None = None,
    ) -> None:
        self.foreign_flow = foreign_flow
        self.fundamentals = fundamentals
        self.market_rs = market_rs
        self.sector_membership = sector_membership
        self.sector_index = sector_index
        self.sector_rs_ranking = sector_rs_ranking
        self.reference_market_date_resolver = reference_market_date_resolver or (lambda target: target)

    def execute(self, target_as_of: str) -> Phase3RunResult:
        target = normalize_target_as_of(target_as_of)
        steps: dict[str, Phase3StepResult] = {}
        reference_market_date: str | None
        reference_error: str | None = None
        try:
            reference_market_date = normalize_target_as_of(self.reference_market_date_resolver(target))
            if reference_market_date > target:
                raise ValueError("REFERENCE_MARKET_DATE_AFTER_TARGET")
        except Exception as exc:  # noqa: BLE001 - missing date authority blocks market inputs
            reference_market_date = None
            reference_error = str(exc) or type(exc).__name__

        def run_market_step(runner: StepRunner) -> Phase3StepResult:
            if reference_market_date is None:
                return Phase3StepResult(
                    BLOCKED,
                    {
                        "reason": "REFERENCE_MARKET_DATE_UNAVAILABLE",
                        "reference_resolution_error": reference_error,
                    },
                )
            return _run_step(runner, target, reference_market_date)

        steps["foreign_flow"] = run_market_step(self.foreign_flow)
        steps["fundamentals"] = _run_step(self.fundamentals, target)
        steps["market_rs"] = run_market_step(self.market_rs)
        membership = run_market_step(self.sector_membership)
        steps["sector_membership"] = membership

        if membership.status in {BLOCKED, FAILED}:
            steps["sector_rs"] = Phase3StepResult(
                membership.status,
                {
                    "reason": "SECTOR_MEMBERSHIP_DEPENDENCY_" + membership.status,
                    "sector_membership_dependency": membership.to_dict(),
                },
            )
        else:
            sector_index = run_market_step(self.sector_index)
            if sector_index.status in {BLOCKED, FAILED}:
                steps["sector_rs"] = Phase3StepResult(
                    sector_index.status,
                    {
                        "reason": "SECTOR_INDEX_DEPENDENCY_" + sector_index.status,
                        "sector_index": sector_index.to_dict(),
                        "sector_membership_dependency": membership.to_dict(),
                    },
                )
            else:
                ranking = run_market_step(self.sector_rs_ranking)
                steps["sector_rs"] = Phase3StepResult(
                    _compose_dependency_status(sector_index.status, ranking.status),
                    {
                        "sector_index": sector_index.to_dict(),
                        "sector_membership_dependency": membership.to_dict(),
                        "sector_rs_ranking": ranking.to_dict(),
                    },
                )

        overall_status = compose_phase3_status(
            {name: steps[name].status for name in TOP_LEVEL_STEPS}
        )
        return Phase3RunResult(target, reference_market_date, overall_status, steps)


def _load_script_module(repo_root: Path, filename: str) -> ModuleType:
    path = Path(repo_root) / "scripts" / filename
    spec = importlib.util.spec_from_file_location(f"phase3_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"SCRIPT_IMPORT_UNAVAILABLE:{filename}")
    module = importlib.util.module_from_spec(spec)
    previous = sys.modules.get(spec.name)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        if previous is None:
            sys.modules.pop(spec.name, None)
        else:
            sys.modules[spec.name] = previous
        raise
    return module


def _foreign_flow_runner(repo_root: Path) -> StepRunner:
    return lambda target, *, reference_market_date: update_foreign_flow_snapshot(
        target,
        repo_root=repo_root,
        reference_market_date=reference_market_date,
    )


def _fundamentals_runner(repo_root: Path, env_file: Path, run_date: str | None) -> StepRunner:
    def run(target: str) -> dict[str, Any]:
        manifest_path = repo_root / "artifacts/fundamentals/production" / target.replace("-", "") / "manifest.json"
        module = None
        if manifest_path.is_file():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if (
                manifest.get("requested_as_of") == target
                and manifest.get("mode") == "full"
                and manifest.get("final_status") == PASS
            ):
                expected_universe, expected_snapshot = load_target_production_universe(repo_root, target)
                expected_tickers = {str(row["ticker"]).strip().upper() for row in expected_universe}
                if (
                    manifest.get("metadata_snapshot_date") == expected_snapshot
                    and int(manifest.get("total_universe", -1)) == len(expected_tickers)
                    and manifest.get("universe_source") == "target_basic_info_and_existing_product_metadata"
                ):
                    module = _load_script_module(repo_root, "hydrate_fundamentals_v1_production.py")
                    output_integrity = module.inspect_target_production_outputs(
                        manifest_path.parent / "tickers",
                        expected_tickers=expected_tickers,
                        requested_as_of=target,
                    )
                    if not any(
                        output_integrity[key]
                        for key in ("missing_count", "extra_count", "invalid_count", "duplicate_count")
                    ):
                        return {
                            "status": NOOP_ALREADY_COMPLETE,
                            "requested_as_of": target,
                            "manifest": str(manifest_path),
                            "output_integrity": output_integrity,
                        }
        if run_date is None:
            raise Phase3BlockedError("FUNDAMENTALS_RUN_DATE_REQUIRED")
        if module is None:
            module = _load_script_module(repo_root, "hydrate_fundamentals_v1_production.py")
        exit_code = module.run(
            "full",
            requested_as_of=target,
            env_file=env_file,
            run_date=run_date,
        )
        if not manifest_path.is_file():
            return {"status": FAILED, "requested_as_of": target, "reason": "FUNDAMENTALS_MANIFEST_MISSING"}
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        final_status = str(manifest.get("final_status", ""))
        if final_status != PASS:
            return {
                "status": FAILED,
                "requested_as_of": target,
                "reason": "FUNDAMENTALS_MANIFEST_FINAL_STATUS_INVALID",
                "manifest_final_status": final_status,
                "manifest": str(manifest_path),
            }
        if exit_code == 0:
            return {"status": PASS, "requested_as_of": target, "manifest": str(manifest_path)}
        return {
            "status": BLOCKED,
            "requested_as_of": target,
            "reason": "FUNDAMENTALS_NOT_COMPLETE",
            "manifest": str(manifest_path),
        }

    return run


def _market_rs_runner(repo_root: Path) -> StepRunner:
    def run(target: str, *, reference_market_date: str) -> Any:
        module = _load_script_module(repo_root, "build_market_rs_snapshot_v01.py")
        return module.build_market_rs_snapshot(
            target,
            repo_root=repo_root,
            reference_market_date=reference_market_date,
        )

    return run


def _sector_membership_runner(repo_root: Path) -> StepRunner:
    def run(target: str, *, reference_market_date: str) -> dict[str, Any]:
        membership, effective_date, path, _meta = resolve_sector_membership_snapshot_for_target(
            reference_market_date,
            repo_root=repo_root,
        )
        target_common = load_local_target_universe(reference_market_date, repo_root=repo_root)
        membership_tickers = set(membership["ticker"].astype(str).str.zfill(6))
        target_tickers = set(target_common["ticker"].astype(str).str.zfill(6))
        membership_markets = dict(
            zip(membership["ticker"].astype(str).str.zfill(6), membership["market"].astype(str).str.upper())
        )
        target_markets = dict(
            zip(target_common["ticker"].astype(str).str.zfill(6), target_common["market"].astype(str).str.upper())
        )
        market_mismatch = sorted(
            ticker
            for ticker in membership_tickers & target_tickers
            if membership_markets[ticker] != target_markets[ticker]
        )
        if market_mismatch:
            raise Phase3BlockedError("TARGET_MEMBERSHIP_MARKET_MISMATCH")
        return {
            "status": NOOP_ALREADY_COMPLETE,
            "target_as_of": target,
            "requested_as_of": target,
            "reference_market_date": reference_market_date,
            "target_common_as_of": reference_market_date,
            "membership_effective_date": effective_date,
            "membership_path": str(path),
            "membership_population": int(len(membership)),
            "target_common_population": int(len(target_common)),
            "target_common_missing_from_membership": int(len(target_tickers - membership_tickers)),
            "membership_not_in_target_common": int(len(membership_tickers - target_tickers)),
        }

    return run


def _sector_index_runner(repo_root: Path) -> StepRunner:
    def run(target: str, *, reference_market_date: str) -> dict[str, Any]:
        result = update_sector_index_rolling(target, repo_root=repo_root).to_dict()
        result["requested_as_of"] = target
        result["reference_market_date"] = reference_market_date
        required_dates = result.get("required_trading_dates") or []
        cache_date_max = result.get("cache_date_max")
        if required_dates and str(required_dates[-1]) != reference_market_date:
            raise Phase3BlockedError("SECTOR_INDEX_REFERENCE_DATE_MISMATCH")
        if result.get("status") in {PASS, NOOP_ALREADY_COMPLETE}:
            if not required_dates or str(required_dates[-1]) != reference_market_date:
                raise Phase3BlockedError("SECTOR_INDEX_REQUIRED_DATES_INCOMPLETE")
            if str(cache_date_max or "") != reference_market_date:
                raise Phase3BlockedError("SECTOR_INDEX_REFERENCE_DATE_MISMATCH")
        return result

    return run


def _sector_rs_ranking_runner(repo_root: Path) -> StepRunner:
    def run(target: str, *, reference_market_date: str) -> dict[str, Any]:
        output_dir = repo_root / "data/analytics/sector_rs_ranking/v01"
        compact = target.replace("-", "")
        parquet_path = output_dir / f"sector_rs_ranking_{compact}.parquet"
        meta_path = output_dir / f"sector_rs_ranking_{compact}_meta.json"
        if parquet_path.is_file() and meta_path.is_file():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            _membership, current_membership_effective_date, _path, _membership_meta = (
                resolve_sector_membership_snapshot_for_target(reference_market_date, repo_root=repo_root)
            )
            frame = pd.read_parquet(parquet_path, columns=["ticker", "market", "as_of"])
            target_common = load_local_target_universe(reference_market_date, repo_root=repo_root)
            expected_tickers = set(target_common["ticker"].astype(str).str.zfill(6))
            expected_markets = dict(
                zip(target_common["ticker"].astype(str).str.zfill(6), target_common["market"].astype(str).str.upper())
            )
            frame["ticker"] = frame["ticker"].astype(str).str.zfill(6)
            frame["market"] = frame["market"].astype(str).str.upper()
            actual_markets = dict(zip(frame["ticker"], frame["market"]))
            if (
                meta.get("requested_as_of", meta.get("as_of")) == target
                and meta.get("reference_market_date", meta.get("as_of")) == reference_market_date
                and meta.get("as_of") == reference_market_date
                and str(meta.get("membership_effective_date", "")) == str(current_membership_effective_date)
                and meta.get("scope", {}).get("type") == "TARGET_PIT_COMMON_POPULATION"
                and int(meta.get("target_common_population", -1)) == len(target_common)
                and len(frame) == len(target_common)
                and frame["ticker"].is_unique
                and frame["as_of"].astype(str).eq(reference_market_date).all()
                and set(frame["ticker"]) == expected_tickers
                and all(actual_markets[ticker] == expected_markets[ticker] for ticker in expected_tickers)
            ):
                return {
                    "status": NOOP_ALREADY_COMPLETE,
                    "target_as_of": target,
                    "requested_as_of": target,
                    "reference_market_date": reference_market_date,
                    "parquet": str(parquet_path),
                    "metadata": str(meta_path),
                }
            raise Phase3BlockedError("EXISTING_SECTOR_RS_ARTIFACT_INVALID")
        module = _load_script_module(repo_root, "build_sector_rs_ranking_v01.py")
        result = module.build_sector_rs_ranking(
            as_of=target,
            reference_market_date=reference_market_date,
            output_dir=output_dir,
        )
        return {
            "status": PASS,
            "target_as_of": target,
            "requested_as_of": target,
            "reference_market_date": reference_market_date,
            **dict(result),
        }

    return run


def build_official_phase3_coordinator(
    *,
    repo_root: Path = ROOT,
    fundamentals_env_file: Path | None = None,
    fundamentals_run_date: str | None = None,
) -> Phase3Coordinator:
    """Build the production coordinator from existing 3A--3F entrypoints."""

    root = Path(repo_root)
    env_file = fundamentals_env_file or root.parent / "env.md"

    def resolve_market_date(target: str) -> str:
        manifest = load_rolling_authority(root / DEFAULT_ROLLING_AUTHORITY_DIR)
        if target > manifest.certified_through:
            raise Phase3BlockedError("TARGET_BEYOND_PHASE1_CERTIFIED_BOUNDARY")
        calendar = load_rolling_production_market_calendar(root)
        reference = resolve_reference_market_date(target, calendar)
        if manifest.merged_calendar_frontier and reference > manifest.merged_calendar_frontier:
            raise Phase3BlockedError("REFERENCE_AFTER_PHASE1_CALENDAR_FRONTIER")
        return reference

    return Phase3Coordinator(
        foreign_flow=_foreign_flow_runner(root),
        fundamentals=_fundamentals_runner(root, env_file, fundamentals_run_date),
        market_rs=_market_rs_runner(root),
        sector_membership=_sector_membership_runner(root),
        sector_index=_sector_index_runner(root),
        sector_rs_ranking=_sector_rs_ranking_runner(root),
        reference_market_date_resolver=resolve_market_date,
    )


__all__ = [
    "BLOCKED",
    "FAILED",
    "NOOP_ALREADY_COMPLETE",
    "PASS",
    "Phase3Coordinator",
    "Phase3RunResult",
    "Phase3StepResult",
    "TOP_LEVEL_STEPS",
    "build_official_phase3_coordinator",
    "compose_phase3_status",
    "normalize_target_as_of",
]
