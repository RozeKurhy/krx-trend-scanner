"""AST regression guard for explicitly listed production Repository V2 entrypoints."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_LOADER = "trend_scanner.data.repository_v2_loader"
REPOSITORY_MODULE = "trend_scanner.data.repository_v2"
RULE_ID = "PROD_REPOSITORY_FACTORY_REQUIRED"
REPLACEMENT = "build_production_repository_v2()"

# Keep this list narrow and evidence-based. Historical research/reproduction
# scripts intentionally remain outside this operational regression guard.
PRODUCTION_ENTRYPOINTS = (
    "scripts/run_daily_update_phase4b_v01.py",
    "scripts/run_daily_update_phase4c_v01.py",
    "scripts/run_daily_update_phase4d_v01.py",
    "scripts/regenerate_stock_reports.py",
    "src/trend_scanner/reporting/stock_report.py",
    "src/trend_scanner/reporting/julia_v1_report.py",
    "scripts/run_pattern_a_universe_scanner.py",
    "src/trend_scanner/scanner/full_universe_scanner.py",
    "scripts/rebuild_fast_web_canonical_alignment_staging_v01.py",
    "scripts/build_sector_rs_ranking_v01.py",
    "scripts/build_market_rs_snapshot_v01.py",
    "scripts/export_etf_ranking_web.py",
    "scripts/export_foreign_net_buy_ranking_web.py",
    "scripts/export_strategy_monitor_web.py",
    "src/trend_scanner/data/daily_update_foundation.py",
)


def _dotted_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _dotted_name(node.value)
        return f"{parent}.{node.attr}" if parent else None
    return None


def _module_aliases(tree: ast.Module) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for imported in node.names:
                bound = imported.asname or imported.name.split(".", 1)[0]
                aliases[bound] = imported.name if imported.asname else imported.name.split(".", 1)[0]
    return aliases


def _resolve_imported_symbol(name: str, module_aliases: dict[str, str]) -> str:
    parts = name.split(".")
    if parts and parts[0] in module_aliases:
        return ".".join([module_aliases[parts[0]], *parts[1:]])
    return name


def _collect_symbols(tree: ast.Module) -> tuple[set[str], set[str], dict[str, str]]:
    module_aliases = _module_aliases(tree)
    forbidden_builders: set[str] = set()
    repository_classes: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module == REPOSITORY_LOADER:
                for imported in node.names:
                    bound = imported.asname or imported.name
                    if imported.name == "build_repository_v2":
                        forbidden_builders.add(bound)
                    elif imported.name == "MarketDataRepositoryV2":
                        repository_classes.add(bound)
            elif node.module == REPOSITORY_MODULE:
                for imported in node.names:
                    if imported.name == "MarketDataRepositoryV2":
                        repository_classes.add(imported.asname or imported.name)

    # Resolve simple local aliases such as ``legacy_factory = build_repository_v2``.
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                value = node.value
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if value is None:
                    continue
                dotted = _dotted_name(value)
                resolved = _resolve_imported_symbol(dotted or "", module_aliases)
                is_builder_alias = (
                    isinstance(value, ast.Name) and value.id in forbidden_builders
                ) or resolved == f"{REPOSITORY_LOADER}.build_repository_v2"
                is_class_alias = (
                    isinstance(value, ast.Name) and value.id in repository_classes
                ) or resolved == f"{REPOSITORY_MODULE}.MarketDataRepositoryV2"
                for target in targets:
                    if isinstance(target, ast.Name):
                        if is_builder_alias and target.id not in forbidden_builders:
                            forbidden_builders.add(target.id)
                            changed = True
                        if is_class_alias and target.id not in repository_classes:
                            repository_classes.add(target.id)
                            changed = True
    return forbidden_builders, repository_classes, module_aliases


def _violations(source: str, filename: str) -> list[str]:
    tree = ast.parse(source, filename=filename)
    forbidden_builders, repository_classes, module_aliases = _collect_symbols(tree)
    errors: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        dotted = _dotted_name(node.func)
        resolved = _resolve_imported_symbol(dotted or "", module_aliases)
        builder_call = (
            isinstance(node.func, ast.Name) and node.func.id in forbidden_builders
        ) or resolved == f"{REPOSITORY_LOADER}.build_repository_v2"
        if builder_call:
            errors.append(
                f"{filename}:{node.lineno}: {RULE_ID}: legacy build_repository_v2 call is forbidden; "
                f"use {REPLACEMENT}"
            )
            continue

        constructor_call = (
            isinstance(node.func, ast.Name) and node.func.id in repository_classes
        ) or resolved == f"{REPOSITORY_MODULE}.MarketDataRepositoryV2"
        if constructor_call:
            rolling_authority = next(
                (keyword.value for keyword in node.keywords if keyword.arg == "rolling_authority_dir"),
                None,
            )
            if rolling_authority is None or (isinstance(rolling_authority, ast.Constant) and rolling_authority.value is None):
                errors.append(
                    f"{filename}:{node.lineno}: {RULE_ID}: direct MarketDataRepositoryV2 construction "
                    f"without rolling_authority_dir is forbidden; use {REPLACEMENT}"
                )
    return errors


def _guarded_source_violations(filename: str, source: str) -> list[str]:
    if filename not in PRODUCTION_ENTRYPOINTS:
        return []
    return _violations(source, filename)


def _production_entrypoint_violations(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    for relative in PRODUCTION_ENTRYPOINTS:
        path = root / relative
        if not path.is_file():
            errors.append(f"{relative}: missing guarded production entrypoint")
            continue
        errors.extend(_guarded_source_violations(relative, path.read_text(encoding="utf-8")))
    return errors


def test_production_entrypoints_use_the_production_repository_factory():
    errors = _production_entrypoint_violations()
    assert not errors, "\n".join(errors)


def test_forbidden_legacy_factory_alias_fails_with_actionable_location():
    source = """from trend_scanner.data.repository_v2_loader import build_repository_v2 as legacy_factory

def run(root):
    return legacy_factory(root, end='2026-10-08')
"""
    errors = _violations(source, "scripts/synthetic_operational_entrypoint.py")
    assert len(errors) == 1
    assert "scripts/synthetic_operational_entrypoint.py:4" in errors[0]
    assert RULE_ID in errors[0]
    assert REPLACEMENT in errors[0]


def test_module_and_assignment_aliases_of_legacy_factory_fail():
    source = """import trend_scanner.data.repository_v2_loader as repository_loader

historical_factory = repository_loader.build_repository_v2
repo = historical_factory(root, end=cutoff)
"""
    errors = _violations(source, "scripts/synthetic_operational_entrypoint.py")
    assert len(errors) == 1
    assert ":4:" in errors[0]
    assert RULE_ID in errors[0]
    assert REPLACEMENT in errors[0]


def test_direct_repository_construction_requires_rolling_authority():
    source = """from trend_scanner.data.repository_v2 import MarketDataRepositoryV2 as Repository

repo = Repository(adjusted, raw)
"""
    errors = _violations(source, "scripts/synthetic_operational_entrypoint.py")
    assert len(errors) == 1
    assert ":3:" in errors[0]
    assert RULE_ID in errors[0]
    assert REPLACEMENT in errors[0]


def test_production_factory_and_authority_bound_repository_are_allowed():
    source = """from trend_scanner.data.repository_v2_loader import build_production_repository_v2
from trend_scanner.data.repository_v2 import MarketDataRepositoryV2

live = build_production_repository_v2(root, end=as_of)
staged = MarketDataRepositoryV2(adjusted, raw, rolling_authority_dir=staged_authority)
"""
    assert _violations(source, "scripts/synthetic_operational_entrypoint.py") == []


def test_historical_research_factory_use_is_outside_guarded_scope():
    research_path = "scripts/run_frozen_historical_reproduction.py"
    source = "from trend_scanner.data.repository_v2_loader import build_repository_v2\nrepo = build_repository_v2(root, end=cutoff)\n"
    assert research_path not in PRODUCTION_ENTRYPOINTS
    assert not _guarded_source_violations(research_path, source)
