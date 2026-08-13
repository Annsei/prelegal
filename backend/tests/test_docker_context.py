"""Fast tripwires for the authoritative BuildKit context check."""

import stat
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTEXT_CHECK = REPO_ROOT / "scripts" / "check-docker-context.sh"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _dockerignore_rules() -> list[str]:
    """Return ordered rules for exact-rule tripwires, not semantic matching."""
    return [
        line.strip()
        for line in (REPO_ROOT / ".dockerignore").read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def test_dockerignore_keeps_explicit_local_only_tripwire_rules():
    """Textual tripwire only; BuildKit owns effective ordered semantics."""
    rules = _dockerignore_rules()

    for required_rule in (
        ".codex/",
        "prelegal.code-workspace",
        "templates/sources/civil-code/",
        ".claude",
        ".env",
        ".env.*",
    ):
        assert required_rule in rules


def test_authoritative_context_check_is_executable_and_wired_before_builds():
    assert CONTEXT_CHECK.is_file()
    assert CONTEXT_CHECK.stat().st_mode & stat.S_IXUSR

    workflow = CI_WORKFLOW.read_text()
    check_position = workflow.index("bash scripts/check-docker-context.sh")
    product_build_position = workflow.index("- name: Build image")
    quality_build_position = workflow.index("- name: Build quality-gate image")
    assert check_position < product_build_position < quality_build_position


def test_effective_context_check_preserves_all_required_product_sources():
    script = CONTEXT_CHECK.read_text()

    for excluded_path in (
        ".codex/config.toml",
        "prelegal.code-workspace",
        "templates/sources/civil-code/PROVENANCE.md",
        "templates/sources/civil-code/sample.pdf",
        "templates/sources/civil-code/sample.txt",
        ".claude/canary.txt",
        ".env",
    ):
        assert excluded_path in script

    for required_path in (
        "templates/manifests/pilot-agreement.json",
        "templates/pilot-agreement/standard_terms.md",
        "backend/app/main.py",
        "frontend/package.json",
        "templates/sources/professional-services-agreement/PROVENANCE.md",
        "templates/sources/professional-services-agreement/"
        "GF-2025-1001-委托合同-原文捕获.txt",
        "templates/sources/data-processing-agreement/PROVENANCE.md",
        "templates/sources/data-processing-agreement/"
        "GF-2025-2616-数据委托处理服务合同-原文捕获.txt",
    ):
        assert required_path in script
