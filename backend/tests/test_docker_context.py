"""Docker build-context exclusion contract tests."""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _dockerignore_rules() -> set[str]:
    return {
        line.strip()
        for line in (REPO_ROOT / ".dockerignore").read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }


def test_docker_context_excludes_local_only_paths_without_hiding_product_inputs():
    rules = _dockerignore_rules()

    local_only = {
        ".codex/",
        "prelegal.code-workspace",
        "templates/sources/civil-code/",
    }
    assert local_only <= rules
    assert {".claude", ".env", ".env.*"} <= rules

    # Official baseline captures and product build inputs remain available.
    assert "templates/" not in rules
    assert "templates/sources/" not in rules
    assert "backend/" not in rules
    assert "frontend/" not in rules
