"""The public entry works without repository imports or third-party packages."""
import json
from pathlib import Path
import subprocess
import sys

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/submit_catalog_chat_intent.py"
INTENT_ID = "018f47a2-6e91-4c34-8000-000000000001"


def test_public_entry_help_is_standalone_without_site_packages(tmp_path):
    result = subprocess.run([sys.executable, "-I", "-S", str(SCRIPT), "--help"], cwd=tmp_path, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert "--campaign-key" in result.stdout


def test_isolated_public_entry_emits_server_compatible_intent(tmp_path):
    from aurora.infra.sp500_megarun.catalog_chat_intent import parse_chat_intent
    inbox = tmp_path / "chat-inbox"
    inbox.mkdir()
    # Only the fixed installation location is replaced for the temporary OS fixture.
    bootstrap = (
        "import importlib.util,sys,pathlib;"
        "s=importlib.util.spec_from_file_location('entry',sys.argv[1]);"
        "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);"
        "m._BROKER_ROOT=pathlib.Path(sys.argv[2]);"
        "sys.argv=['entry','--campaign-key','sp500-optimized-catalog-v1','--intent-id',sys.argv[3]];"
        "raise SystemExit(m.main())"
    )
    result = subprocess.run([sys.executable, "-I", "-S", "-c", bootstrap, str(SCRIPT), str(tmp_path), INTENT_ID], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "pending"
    observed = parse_chat_intent((inbox / f"{INTENT_ID}.intent.json").read_bytes())
    assert observed.intent_id == INTENT_ID
    assert observed.campaign_key == "sp500-optimized-catalog-v1"
