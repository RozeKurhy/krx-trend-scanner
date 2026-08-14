import dataclasses

from trend_scanner.patterns.pattern_a_feature_set import (
    ALREADY_PROGRESSED_CANDIDATE_SIGNALS,
    BASE_CONTEXT_FEATURES,
    DIAGNOSTIC_FEATURES,
    DROPPED_FEATURES,
    FEATURE_AXES,
    FEATURE_ROLES,
    PATTERN_A_FEATURE_SCOPE,
    STAGE_CONTEXT_FEATURES,
    TRANSITION_CORE_FEATURES,
    TRANSITION_SUPPORTING_FEATURES,
    FeatureAxis,
    FeatureRole,
)
from trend_scanner.validation.feature_report import FeatureRow

_ROLE_SETS = [
    TRANSITION_CORE_FEATURES,
    TRANSITION_SUPPORTING_FEATURES,
    BASE_CONTEXT_FEATURES,
    STAGE_CONTEXT_FEATURES,
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
    expected = {name: FeatureRole.CORE for name in TRANSITION_CORE_FEATURES}
    expected.update({name: FeatureRole.SUPPORTING for name in TRANSITION_SUPPORTING_FEATURES})
    expected.update({name: FeatureRole.CONTEXT for name in BASE_CONTEXT_FEATURES})
    expected.update({name: FeatureRole.CONTEXT for name in STAGE_CONTEXT_FEATURES})
    expected.update({name: FeatureRole.DIAGNOSTIC for name in DIAGNOSTIC_FEATURES})
    expected.update({name: FeatureRole.DROP for name in DROPPED_FEATURES})

    assert FEATURE_ROLES == expected


def test_feature_roles_dict_has_no_duplicate_assignment():
    # 6개 role 집합을 합친 길이와 dict 길이가 같아야 한다 -> 어떤 Feature도
    # 두 role에 동시에 들어가지 않았다는 뜻이다(위 disjoint 테스트와 이중 확인).
    total_in_sets = sum(len(s) for s in _ROLE_SETS)
    assert total_in_sets == len(FEATURE_ROLES)


def test_pattern_a_feature_scope_matches_classified_features_exactly():
    # PATTERN_A_FEATURE_SCOPE는 role 집합에서 파생하지 않고 독립적으로
    # 나열된 ground truth다 -> 이 비교가 "scope엔 있는데 role이 없는 경우"와
    # "role은 있는데 scope 나열에서 빠진 경우"를 둘 다 잡는다.
    classified_features = set().union(*_ROLE_SETS)
    assert classified_features == PATTERN_A_FEATURE_SCOPE


def test_feature_axes_domain_is_scope_minus_diagnostic_and_dropped():
    expected_domain = PATTERN_A_FEATURE_SCOPE - DIAGNOSTIC_FEATURES - DROPPED_FEATURES
    assert set(FEATURE_AXES) == expected_domain


def test_feature_axes_values_match_their_role_set():
    for name in TRANSITION_CORE_FEATURES | TRANSITION_SUPPORTING_FEATURES:
        assert FEATURE_AXES[name] == FeatureAxis.TRANSITION, name
    for name in BASE_CONTEXT_FEATURES:
        assert FEATURE_AXES[name] == FeatureAxis.BASE, name
    for name in STAGE_CONTEXT_FEATURES:
        assert FEATURE_AXES[name] == FeatureAxis.STAGE, name


def test_already_progressed_candidate_signals_are_known_and_classified_features():
    for name in ALREADY_PROGRESSED_CANDIDATE_SIGNALS:
        assert name in _FEATURE_ROW_FIELD_NAMES, f"FeatureRow에 없는 이름: {name}"
        assert name in FEATURE_ROLES, f"role 분류가 안 된 이름: {name}"
