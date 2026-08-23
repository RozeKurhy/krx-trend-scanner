"""Filing-specific XBRL ZIP cache, provenance, and minimal fact extraction."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree as ET

from .models import RawXbrlArtifact, RegisteredFiling
from .opendart_client import BinaryResponse, OpenDartClient
from .opendart_contract import REPORT_TYPE_BY_CODE


class XbrlRepositoryError(RuntimeError):
    pass


class SourceMutationDetected(XbrlRepositoryError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _prefix(namespace: str) -> str:
    if "xbrl.ifrs.org/taxonomy" in namespace:
        return "ifrs-full"
    if "dart-gcd" in namespace:
        return "dart-gcd"
    if "dart.fss.or.kr/taxonomy" in namespace:
        return "dart"
    return namespace.rsplit("/", 1)[-1] or "xbrl"


def _parse_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _text(element: ET.Element, child_name: str) -> str | None:
    for child in element.iter():
        if _local(child.tag) == child_name:
            return (child.text or "").strip() or None
    return None


def _context_info(context: ET.Element) -> dict[str, Any]:
    members = [
        {"dimension": item.get("dimension"), "member": (item.text or "").strip()}
        for item in context.iter() if _local(item.tag) == "explicitMember"
    ]
    instant = _text(context, "instant")
    start = _text(context, "startDate")
    end = _text(context, "endDate") or instant
    duration_days = None
    try:
        if start and end and start <= end:
            duration_days = (datetime.fromisoformat(end) - datetime.fromisoformat(start)).days + 1
    except ValueError:
        duration_days = None
    basis = next((item["member"].split(":")[-1] for item in members
                  if item["dimension"] and item["dimension"].split(":")[-1] == "ConsolidatedAndSeparateFinancialStatementsAxis"), None)
    return {
        "id": context.get("id"), "start": start, "end": end, "instant": instant,
        "duration_days": duration_days,
        "context_semantics": "INSTANT" if instant and not start else "UNKNOWN",
        "members": members, "basis": basis,
        "primary": len(members) <= 1 and basis in {"ConsolidatedMember", "SeparateMember"},
    }


def _numeric_value(text: str | None) -> int | None:
    value = str(text or "").strip().replace(",", "")
    if value in {"", "-", "—", "–"}:
        return None
    try:
        return int(value)
    except ValueError:
        return None


class XbrlRepository:
    def __init__(self, client: OpenDartClient | None = None, *, cache_dir: Path | str = "data/cache/opendart/xbrl"):
        self.client = client
        self.cache_dir = Path(cache_dir)
        self.last_fetch: RawXbrlArtifact | None = None

    def _paths(self, rcept_no: str, reprt_code: str) -> tuple[Path, Path]:
        stem = f"{rcept_no}_{reprt_code}"
        return self.cache_dir / f"{stem}.zip", self.cache_dir / f"{stem}.json"

    def _from_metadata(self, payload: dict[str, Any], *, cache_hit: bool) -> RawXbrlArtifact:
        return RawXbrlArtifact(
            corp_code=str(payload["corp_code"]), ticker=str(payload["ticker"]),
            rcept_no=str(payload["rcept_no"]), reprt_code=str(payload["reprt_code"]),
            rcept_dt=str(payload["rcept_dt"]), retrieved_at=str(payload["retrieved_at"]),
            http_status=int(payload["http_status"]), content_type=payload.get("content_type"),
            byte_length=int(payload["byte_length"]), sha256=str(payload["sha256"]),
            member_count=int(payload["member_count"]), member_names=tuple(payload.get("member_names", [])),
            source_url_redacted=str(payload["source_url_redacted"]), cache_hit=cache_hit,
        )

    def _load_cached(self, filing: RegisteredFiling) -> tuple[RawXbrlArtifact, bytes] | None:
        zip_path, meta_path = self._paths(filing.rcept_no, filing.reprt_code)
        if not zip_path.exists() or not meta_path.exists():
            return None
        payload = json.loads(meta_path.read_text(encoding="utf-8"))
        raw = zip_path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != payload.get("sha256") or not zipfile.is_zipfile(io.BytesIO(raw)):
            raise XbrlRepositoryError("Cached XBRL artifact failed SHA/ZIP validation")
        return self._from_metadata(payload, cache_hit=True), raw

    def fetch(self, filing: RegisteredFiling, *, force_refresh: bool = False) -> RawXbrlArtifact:
        cached = None if force_refresh else self._load_cached(filing)
        if cached is not None:
            self.last_fetch = cached[0]
            return cached[0]
        if self.client is None:
            raise XbrlRepositoryError("OpenDART client is required for XBRL fetch")
        response: BinaryResponse = self.client.xbrl(filing.rcept_no, filing.reprt_code)
        raw = response.raw
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            names = tuple(archive.namelist())
        sha = hashlib.sha256(raw).hexdigest()
        zip_path, meta_path = self._paths(filing.rcept_no, filing.reprt_code)
        if zip_path.exists() and meta_path.exists():
            old = json.loads(meta_path.read_text(encoding="utf-8"))
            if old.get("sha256") != sha:
                raise SourceMutationDetected(f"XBRL source mutation for {filing.rcept_no}; old/new SHA differ")
        artifact = RawXbrlArtifact(
            corp_code=filing.corp_code, ticker=filing.ticker, rcept_no=filing.rcept_no,
            reprt_code=filing.reprt_code, rcept_dt=filing.rcept_dt, retrieved_at=_now(),
            http_status=response.http_status, content_type=response.content_type,
            byte_length=len(raw), sha256=sha, member_count=len(names), member_names=names,
            source_url_redacted=response.request_url_redacted, cache_hit=False,
        )
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        zip_path.write_bytes(raw)
        meta_path.write_text(json.dumps(artifact.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        self.last_fetch = artifact
        return artifact

    def read_member(self, artifact: RawXbrlArtifact, member_name: str) -> bytes:
        zip_path, _ = self._paths(artifact.rcept_no, artifact.reprt_code)
        with zipfile.ZipFile(zip_path) as archive:
            return archive.read(member_name)

    def statement_rows(self, artifact: RawXbrlArtifact, *, bsns_year: str, reprt_code: str,
                       preferred_basis: str = "CFS") -> list[dict[str, Any]]:
        """Extract only primary consolidated/separate facts needed by V01.

        The parser deliberately does not attempt generic taxonomy or linkbase
        reconstruction.  Facts remain raw rows and are filtered by period,
        primary statement context, and explicit metric IDs downstream.
        """
        zip_path, _ = self._paths(artifact.rcept_no, artifact.reprt_code)
        with zipfile.ZipFile(zip_path) as archive:
            xbrl_names = [name for name in archive.namelist() if name.lower().endswith(".xbrl")]
            if not xbrl_names:
                raise XbrlRepositoryError("Filing ZIP has no XBRL instance document")
            root = ET.fromstring(archive.read(xbrl_names[0]))
        contexts = {
            item.get("id"): _context_info(item)
            for item in root if _local(item.tag) == "context" and item.get("id")
        }
        target_ids = {
            "ifrs-full_Assets", "ifrs-full_Liabilities", "ifrs-full_Equity", "ifrs-full_Revenue",
            "dart_OperatingIncomeLoss", "ifrs-full_ProfitLoss",
            "ifrs-full_ProfitLossFromOperatingActivities",
            "ifrs-full_CashFlowsFromUsedInOperatingActivities",
        }
        names = {
            "ifrs-full_Assets": "자산총계", "ifrs-full_Liabilities": "부채총계", "ifrs-full_Equity": "자본총계",
            "ifrs-full_Revenue": "매출액", "dart_OperatingIncomeLoss": "영업이익",
            "ifrs-full_ProfitLossFromOperatingActivities": "영업이익", "ifrs-full_ProfitLoss": "당기순이익",
            "ifrs-full_CashFlowsFromUsedInOperatingActivities": "영업활동현금흐름",
        }
        primary_contexts = [item for item in contexts.values() if item["primary"] and item.get("end")]
        filing_end = _parse_date(artifact.rcept_dt)
        if filing_end:
            primary_contexts = [item for item in primary_contexts
                                if not _parse_date(item.get("end")) or _parse_date(item.get("end")) <= filing_end]
        available_ends = sorted({str(item["end"]) for item in primary_contexts if item.get("end")})
        actual_end = available_ends[-1] if available_ends else None
        rows: list[dict[str, Any]] = []
        for fact in root:
            context_ref = fact.get("contextRef")
            if not context_ref or context_ref not in contexts:
                continue
            context = contexts[context_ref]
            if not actual_end or context["end"] != actual_end or not context["primary"]:
                continue
            namespace = fact.tag.split("}", 1)[0].lstrip("{") if "}" in fact.tag else ""
            account_id = f"{_prefix(namespace)}_{_local(fact.tag)}"
            if account_id not in target_ids:
                continue
            value = _numeric_value(fact.text)
            family = "BALANCE_SHEET" if account_id in {"ifrs-full_Assets", "ifrs-full_Liabilities", "ifrs-full_Equity"} else (
                "CASH_FLOW" if account_id == "ifrs-full_CashFlowsFromUsedInOperatingActivities" else "INCOME_STATEMENT"
            )
            raw_sj = "CF" if family == "CASH_FLOW" else ("BS" if family == "BALANCE_SHEET" else "CIS")
            rows.append({
                "account_id": account_id,
                "account_nm": names.get(account_id),
                "sj_div": raw_sj,
                "statement_family": family,
                "account_detail": None,
                "thstrm_amount": fact.text,
                "value": value,
                "currency": fact.get("unitRef"),
                "ord": len(rows),
                "context_ref": context_ref,
                "period_start": context["start"],
                "period_end": context["end"],
                "instant": context["instant"],
                "duration_days": context["duration_days"],
                "context_semantics": context["context_semantics"],
                "basis": context["basis"],
            })
        return rows

    def period_context_rows(self, artifact: RawXbrlArtifact, *, bsns_year: str, reprt_code: str,
                            preferred_basis: str = "CFS") -> list[dict[str, Any]]:
        """Return all filing-specific primary metric contexts for periodization.

        Unlike :meth:`statement_rows`, this method intentionally retains both
        current and comparative contexts.  Comparative rows are marked so the
        periodization layer can exclude them without treating a first match as
        current.  No calendar-quarter date is used as authority.
        """
        zip_path, _ = self._paths(artifact.rcept_no, artifact.reprt_code)
        with zipfile.ZipFile(zip_path) as archive:
            xbrl_names = [name for name in archive.namelist() if name.lower().endswith(".xbrl")]
            if not xbrl_names:
                raise XbrlRepositoryError("Filing ZIP has no XBRL instance document")
            root = ET.fromstring(archive.read(xbrl_names[0]))
        contexts = {
            item.get("id"): _context_info(item)
            for item in root if _local(item.tag) == "context" and item.get("id")
        }
        target_ids = {
            "ifrs-full_Assets", "ifrs-full_Liabilities", "ifrs-full_Equity", "ifrs-full_Revenue",
            "dart_OperatingIncomeLoss", "ifrs-full_ProfitLoss",
            "ifrs-full_ProfitLossFromOperatingActivities",
            "ifrs-full_CashFlowsFromUsedInOperatingActivities",
        }
        names = {
            "ifrs-full_Assets": "자산총계", "ifrs-full_Liabilities": "부채총계", "ifrs-full_Equity": "자본총계",
            "ifrs-full_Revenue": "매출액", "dart_OperatingIncomeLoss": "영업이익",
            "ifrs-full_ProfitLossFromOperatingActivities": "영업이익", "ifrs-full_ProfitLoss": "당기순이익",
            "ifrs-full_CashFlowsFromUsedInOperatingActivities": "영업활동현금흐름",
        }
        primary_contexts = [item for item in contexts.values() if item["primary"] and item.get("end")]
        filing_end = _parse_date(artifact.rcept_dt)
        if filing_end:
            primary_contexts = [item for item in primary_contexts
                                if not _parse_date(item.get("end")) or _parse_date(item.get("end")) <= filing_end]
        latest_end_by_basis: dict[str | None, str] = {}
        for context in primary_contexts:
            basis = context.get("basis")
            end = str(context.get("end") or "")
            if end > latest_end_by_basis.get(basis, ""):
                latest_end_by_basis[basis] = end
        rows: list[dict[str, Any]] = []
        for fact in root:
            context_ref = fact.get("contextRef")
            if not context_ref or context_ref not in contexts:
                continue
            context = contexts[context_ref]
            if context not in primary_contexts:
                continue
            namespace = fact.tag.split("}", 1)[0].lstrip("{") if "}" in fact.tag else ""
            account_id = f"{_prefix(namespace)}_{_local(fact.tag)}"
            if account_id not in target_ids:
                continue
            family = "BALANCE_SHEET" if account_id in {"ifrs-full_Assets", "ifrs-full_Liabilities", "ifrs-full_Equity"} else (
                "CASH_FLOW" if account_id == "ifrs-full_CashFlowsFromUsedInOperatingActivities" else "INCOME_STATEMENT"
            )
            raw_sj = "CF" if family == "CASH_FLOW" else ("BS" if family == "BALANCE_SHEET" else "CIS")
            rows.append({
                "ticker": artifact.ticker, "corp_code": artifact.corp_code, "bsns_year": str(bsns_year),
                "reprt_code": str(reprt_code), "report_type": REPORT_TYPE_BY_CODE.get(str(reprt_code), "UNKNOWN"),
                "account_id": account_id, "account_nm": names.get(account_id), "sj_div": raw_sj,
                "statement_family": family, "account_detail": None, "thstrm_amount": fact.text,
                "value": _numeric_value(fact.text), "currency": fact.get("unitRef"), "ord": len(rows),
                "context_ref": context_ref, "period_start": context["start"], "period_end": context["end"],
                "instant": context["instant"], "duration_days": context["duration_days"],
                "context_semantics": context["context_semantics"],
                "comparative": str(context.get("end")) != latest_end_by_basis.get(context.get("basis")),
                "basis": context["basis"], "rcept_no": artifact.rcept_no, "rcept_dt": artifact.rcept_dt,
                "source_sha256": artifact.sha256,
            })
        return rows

    def basis_rows(self, rows: Iterable[dict[str, Any]], preferred_basis: str = "CFS",
                   *, cfs_status: str | None = None, ofs_status: str | None = None) -> tuple[str, list[dict[str, Any]]]:
        values = list(rows)
        preferred = [row for row in values if row.get("basis") == "ConsolidatedMember"]
        separate = [row for row in values if row.get("basis") == "SeparateMember"]
        if preferred:
            return "CFS", preferred
        # An OFS fallback is valid only after the CFS endpoint explicitly
        # reports DATA_NOT_FOUND (013); an absent/failed CFS response must not
        # be silently replaced by separate-statement rows.
        if separate and cfs_status == "013" and ofs_status == "000":
            return "OFS", separate
        return "", []
