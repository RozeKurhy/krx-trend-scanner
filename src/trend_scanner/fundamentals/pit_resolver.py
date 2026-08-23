"""Production wrapper around the architecture PIT selection contract."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable, Mapping

from .filing_registry import RegisteredFiling, _to_contract, to_registered_filing
from .opendart_contract import FilingRecord, FilingSelection, select_pit_filing


@dataclass(frozen=True)
class PITResolution:
    status: str
    selected_rcept_no: str | None
    selected_rcept_dt: str | None
    availability: str | None
    eligible_count: int
    future_count: int
    filing_chain_key: str | None
    selected: RegisteredFiling | None
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "selected_rcept_no": self.selected_rcept_no,
            "selected_rcept_dt": self.selected_rcept_dt,
            "availability": self.availability,
            "eligible_count": self.eligible_count,
            "future_count": self.future_count,
            "filing_chain_key": self.filing_chain_key,
            "selected": self.selected.to_dict() if self.selected else None,
            "reason": self.reason,
        }


class PITResolver:
    def resolve(self, filings: Iterable[RegisteredFiling | FilingRecord | Mapping[str, object]], *, as_of: str | date,
                bsns_year: str, reprt_code: str) -> PITResolution:
        source = list(filings)
        contract_rows: list[FilingRecord | Mapping[str, object]] = []
        for item in source:
            if isinstance(item, RegisteredFiling):
                contract_rows.append(_to_contract(item))
            else:
                contract_rows.append(item)
        selected = select_pit_filing(contract_rows, as_of, str(bsns_year), str(reprt_code))
        selected_public = None
        if selected.selected is not None:
            for item in source:
                if isinstance(item, RegisteredFiling) and item.rcept_no == selected.selected.rcept_no:
                    selected_public = item
                    break
                if isinstance(item, FilingRecord) and item.rcept_no == selected.selected.rcept_no:
                    selected_public = RegisteredFiling(
                        ticker=item.ticker, corp_code=item.corp_code, corp_name="", bsns_year=item.bsns_year,
                        reprt_code=item.reprt_code, report_type=item.report_type or "UNKNOWN", report_nm=item.report_nm,
                        rcept_no=item.rcept_no, rcept_dt=item.rcept_dt,
                        filing_chain_key=item.derived_chain_key or "", correction_flag=False,
                        source_retrieved_at="", fs_div=item.fs_div,
                    )
                    break
                if isinstance(item, Mapping) and str(item.get("rcept_no") or "") == selected.selected.rcept_no:
                    selected_public = to_registered_filing(dict(item), ticker=str(item.get("ticker") or ""), retrieved_at="")
                    break
        return PITResolution(
            status=selected.status,
            selected_rcept_no=selected.selected.rcept_no if selected.selected else None,
            selected_rcept_dt=selected.selected.rcept_dt if selected.selected else None,
            availability=selected.availability,
            eligible_count=len(selected.eligible),
            future_count=len(selected.future),
            filing_chain_key=selected.selected.derived_chain_key if selected.selected else None,
            selected=selected_public,
            reason=selected.reason,
        )

    def resolve_selection(self, filings: Iterable[RegisteredFiling | FilingRecord | Mapping[str, object]], *, as_of: str | date,
                          bsns_year: str, reprt_code: str) -> FilingSelection:
        rows = [_to_contract(item) if isinstance(item, RegisteredFiling) else item for item in filings]
        return select_pit_filing(rows, as_of, str(bsns_year), str(reprt_code))
