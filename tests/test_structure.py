"""Basic structure tests that don't require Home Assistant."""
import json
from pathlib import Path


def test_manifest_exists():
    """Test that manifest.json exists and is valid."""
    manifest_path = Path("custom_components/saxo_portfolio/manifest.json")
    assert manifest_path.exists(), "manifest.json should exist"

    with open(manifest_path) as f:
        manifest = json.load(f)

    # Required fields
    required_fields = ["domain", "name", "codeowners", "documentation", "issue_tracker", "version"]
    for field in required_fields:
        assert field in manifest, f"manifest.json should have {field} field"

    assert manifest["domain"] == "saxo_portfolio"
    assert "github.com" in manifest["documentation"]
    assert "github.com" in manifest["issue_tracker"]


def test_required_files_exist():
    """Test that required files exist."""
    required_files = [
        "custom_components/saxo_portfolio/__init__.py",
        "custom_components/saxo_portfolio/sensor.py",
        "custom_components/saxo_portfolio/config_flow.py",
        "custom_components/saxo_portfolio/coordinator.py",
        "custom_components/saxo_portfolio/const.py",
        "custom_components/saxo_portfolio/models.py",
        "README.md",
        "hacs.json",
        "LICENSE",
        "CHANGELOG.md"
    ]

    for file_path in required_files:
        assert Path(file_path).exists(), f"{file_path} should exist"


def test_hacs_json_valid():
    """Test that hacs.json is valid."""
    hacs_path = Path("hacs.json")
    assert hacs_path.exists(), "hacs.json should exist"

    with open(hacs_path) as f:
        hacs_config = json.load(f)

    assert "name" in hacs_config
    assert hacs_config["name"] == "Saxo Portfolio"
    assert hacs_config.get("content_in_root") is False


def test_github_workflows_exist():
    """Test that GitHub workflows exist."""
    workflow_files = [
        ".github/workflows/hacs.yml",
        ".github/workflows/hassfest.yml"
    ]

    for workflow in workflow_files:
        assert Path(workflow).exists(), f"{workflow} should exist"


def test_basic_python_syntax():
    """Test that Python files have valid syntax."""
    python_files = [
        "custom_components/saxo_portfolio/__init__.py",
        "custom_components/saxo_portfolio/sensor.py",
        "custom_components/saxo_portfolio/config_flow.py",
        "custom_components/saxo_portfolio/coordinator.py",
        "custom_components/saxo_portfolio/const.py",
        "custom_components/saxo_portfolio/models.py"
    ]

    for file_path in python_files:
        with open(file_path) as f:
            content = f.read()

        # Basic syntax check - compile the code
        try:
            compile(content, file_path, 'exec')
        except SyntaxError as e:
            assert False, f"Syntax error in {file_path}: {e}"
