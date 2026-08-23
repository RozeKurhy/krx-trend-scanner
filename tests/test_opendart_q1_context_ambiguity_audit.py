from __future__ import annotations

from scripts.audit_opendart_q1_context_ambiguity import classify_context_group, semantic_fingerprint


def _row(*, context: str, value: int, dimensions=None, concept="ifrs-full_Revenue"):
    row = {
        "ticker": "TEST", "fiscal_year": "2025", "metric": "revenue", "concept": concept,
        "period_start": "2025-01-01", "period_end": "2025-03-31", "instant": None,
        "fs_div_used": "CFS", "currency": "KRW", "unit": "KRW", "entity_identifier": "001",
        "dimensions_normalized": dimensions or [], "segment_present": False, "scenario_present": False,
        "period_semantics": "CUMULATIVE_YTD", "comparative": False, "context_id": context,
        "value": value, "has_dimensions": bool(dimensions),
    }
    row["semantic_fingerprint"] = semantic_fingerprint(row)
    return row


def test_identical_semantic_fingerprint_and_value_is_exact_duplicate():
    assert classify_context_group([_row(context="A", value=100), _row(context="B", value=100)]) == "EXACT_SEMANTIC_DUPLICATE"


def test_same_fingerprint_with_different_value_is_unsafe_conflict():
    left = _row(context="A", value=100)
    right = _row(context="B", value=101)
    assert semantic_fingerprint(left) == semantic_fingerprint(right)
    assert classify_context_group([left, right]) == "VALUE_DIFFERENT_SEMANTICALLY_DIFFERENT"


def test_dimension_difference_is_not_value_only_deduplication():
    rows = [_row(context="A", value=100), _row(context="B", value=100, dimensions=[{"dimension": "SegmentAxis", "member": "Member"}])]
    assert classify_context_group(rows) == "PRIMARY_TOTAL_PLUS_DIMENSIONED_DETAIL"


def test_same_context_duplicate_fact_is_parser_duplicate_candidate():
    assert classify_context_group([_row(context="A", value=100), _row(context="A", value=100)]) == "PARSER_DUPLICATION"


def test_concept_alias_remains_semantically_visible_in_fingerprint():
    left = _row(context="A", value=100, concept="dart_OperatingIncomeLoss")
    right = _row(context="B", value=100, concept="ifrs-full_ProfitLossFromOperatingActivities")
    assert semantic_fingerprint(left) != semantic_fingerprint(right)
