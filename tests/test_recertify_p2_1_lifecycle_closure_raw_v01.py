import pandas as pd

import scripts.recertify_p2_1_lifecycle_closure_raw_v01 as closure
import scripts.run_fastcore_neg40_weak_protect_p2_1 as runner
from trend_scanner.universe.permanent_identity_exclusions import PERMANENT_IDENTITY_EXCLUSIONS


def test_closure_exclusions_are_exact_identities_outside_the_shared_registry():
    keys = set(closure.P2_1_LIFECYCLE_CLOSURE_EXCLUSIONS)
    assert len(keys) == 7
    assert all(len(ticker) == 6 and isu.startswith("KR") and len(isu) == 12 for ticker, isu in keys)
    assert not keys & set(PERMANENT_IDENTITY_EXCLUSIONS)
    assert ("096300", "KR7096300009") not in keys
    assert closure.EXPECTED_REGISTRY_RAW_IDENTITIES <= set(PERMANENT_IDENTITY_EXCLUSIONS)


def test_label_marks_only_sealed_096300_liquidation_as_authoritative_final():
    frame = pd.DataFrame(
        [
            {
                "pair_id": closure.ALLOWED_FINAL_UNRESOLVED_PAIR_ID,
                "lifecycle_state": "UNRESOLVED_SETTLEMENT",
                "lifecycle_event_type": "LIQUIDATION_UNRESOLVED",
                "lifecycle_source_isu_cd": "KR7096300009",
                "lifecycle_evidence_id": "KRX-LIFECYCLE-KR7096300009",
            },
            {
                "pair_id": "other-liquidation",
                "lifecycle_state": "UNRESOLVED_SETTLEMENT",
                "lifecycle_event_type": "LIQUIDATION_UNRESOLVED",
                "lifecycle_source_isu_cd": "KR7000000001",
                "lifecycle_evidence_id": "KRX-LIFECYCLE-KR7000000001",
            },
            {
                "pair_id": "successor",
                "lifecycle_state": "UNRESOLVED_SUCCESSOR",
                "lifecycle_event_type": "MANDATORY_SHARE_EXCHANGE",
                "lifecycle_source_isu_cd": "KR7008560005",
                "lifecycle_evidence_id": "KRX-LIFECYCLE-KR7008560005",
            },
            {
                "pair_id": "settled",
                "lifecycle_state": "SETTLED",
                "lifecycle_event_type": "MANDATORY_CASH_CORPORATE_ACTION",
                "lifecycle_source_isu_cd": "KR7115390007",
                "lifecycle_evidence_id": "KRX-LIFECYCLE-KR7115390007",
            },
        ]
    )

    labeled = closure.label_authoritative_final(frame).set_index("pair_id")["lifecycle_certification_class"]

    assert labeled[closure.ALLOWED_FINAL_UNRESOLVED_PAIR_ID] == runner.AUTHORITATIVE_FINAL_UNRESOLVED
    assert labeled["other-liquidation"] == runner.REMEDIABLE_UNRESOLVED
    assert labeled["successor"] == runner.REMEDIABLE_UNRESOLVED
    assert pd.isna(labeled["settled"])
    assert "lifecycle_certification_class" not in frame.columns


def test_gate_fields_are_namespaced_for_p2_1():
    renamed = closure.rename_gate_fields(
        {"p3_1_effective_remediable_unresolved_count": 0, "duplicate_pair_ids": 0}
    )
    assert renamed == {"p2_1_effective_remediable_unresolved_count": 0, "duplicate_pair_ids": 0}
