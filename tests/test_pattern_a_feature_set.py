import dataclasses

from trend_scanner.patterns.pattern_a_feature_set import (
    ALREADY_PROGRESSED_CANDIDATE_SIGNALS,
    CORE_FEATURES,
    DIAGNOSTIC_FEATURES,
    DROPPED_FEATURES,
    FEATURE_ROLES,
    STAGE_FEATURES,
    SUPPORTING_FEATURES,
    FeatureRole,
)
from trend_scanner.validation.feature_report import FeatureRow

_ROLE_SETS = [
    CORE_FEATURES,
    SUPPORTING_FEATURES,
    STAGE_FEATURES,
    DIAGNOSTIC_FEATURES,
    DROPPED_FEATURES,
]

_FEATURE_ROW_FIELD_NAMES = {f.name for f in dataclasses.fields(FeatureRow)}


def test_role_sets_are_pairwise_disjoint():
    for i, a in enumerate(_ROLE_SETS):
        for b in _ROLE_SETS[i + 1 :]:
            assert a.isdisjoint(b), f"겹치는 Feature 발견: {a & b}"


def test_every_classified_feature_is_a_real_featurerow_field():
    all_classified = set().union(*_ROLE_SETS)
    unknown = all_classified - _FEATURE_ROW_FIELD_NAMES
    assert not unknown, f"FeatureRow에 없는 이름: {unknown}"


def test_feature_roles_dict_matches_role_sets_exactly():
    expected = {name: FeatureRole.CORE for name in CORE_FEATURES}
    expected.update({name: FeatureRole.SUPPORTING for name in SUPPORTING_FEATURES})
    expected.update({name: FeatureRole.STAGE for name in STAGE_FEATURES})
    expected.update({name: FeatureRole.DIAGNOSTIC for name in DIAGNOSTIC_FEATURES})
    expected.update({name: FeatureRole.DROP for name in DROPPED_FEATURES})

    assert FEATURE_ROLES == expected


def test_feature_roles_dict_has_no_duplicate_assignment():
    # 5개 role 집합을 합친 길이와 dict 길이가 같아야 한다 -> 어떤 Feature도
    # 두 role에 동시에 들어가지 않았다는 뜻이다(위 disjoint 테스트와 이중 확인).
    total_in_sets = sum(len(s) for s in _ROLE_SETS)
    assert total_in_sets == len(FEATURE_ROLES)


def test_already_progressed_candidate_signals_are_known_and_classified_features():
    for name in ALREADY_PROGRESSED_CANDIDATE_SIGNALS:
        assert name in _FEATURE_ROW_FIELD_NAMES, f"FeatureRow에 없는 이름: {name}"
        assert name in FEATURE_ROLES, f"role 분류가 안 된 이름: {name}"
