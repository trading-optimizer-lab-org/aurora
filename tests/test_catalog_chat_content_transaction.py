"""Black-box Windows tests for the catalog chat content transaction."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "scripts/catalog_chat_content_transaction.psm1"


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _run_ps(tmp_path: Path, setup: str, files: str, *, patch: str = "", after_transaction: str = "") -> dict:
    shell = shutil.which("powershell")
    if shell is None:
        pytest.skip("Windows PowerShell required")
    script = tmp_path / "transaction-fixture.ps1"
    script.write_text(
        """
$ErrorActionPreference = 'Stop'
$base = $PSScriptRoot
$payload = Join-Path $base 'payload'
$target = Join-Path $base 'target'
$backup = Join-Path $base 'backup'
New-Item -ItemType Directory -Force -Path $payload, $target | Out-Null
SETUP
$module = Import-Module MODULE -PassThru
PATCH
$files = @(
FILES
)
$before = @{}
$aclBefore = @{}
foreach ($relative in @('first.txt', 'second.txt', 'third.txt', 'long.txt')) {
    $path = Join-Path $target $relative
    if (Test-Path -LiteralPath $path -PathType Leaf) {
        $before[$relative] = [Convert]::ToBase64String([IO.File]::ReadAllBytes($path))
        $aclBefore[$relative] = ([IO.FileInfo]::new($path)).GetAccessControl().GetSecurityDescriptorSddlForm([Security.AccessControl.AccessControlSections]::All)
    }
}
$result = Invoke-CatalogChatContentTransaction -PayloadRoot $payload -TargetRoot $target -BackupRoot $backup -Files $files
$restore = $null
AFTER_TRANSACTION
$journal = $null
if ($result.journal_path -and (Test-Path -LiteralPath $result.journal_path -PathType Leaf)) {
    $journal = Get-Content -LiteralPath $result.journal_path -Raw | ConvertFrom-Json
}
$after = @{}
$aclAfter = @{}
foreach ($relative in @('first.txt', 'second.txt', 'third.txt', 'long.txt', 'new.txt')) {
    $path = Join-Path $target $relative
    if (Test-Path -LiteralPath $path -PathType Leaf) {
        $after[$relative] = [Convert]::ToBase64String([IO.File]::ReadAllBytes($path))
        $aclAfter[$relative] = ([IO.FileInfo]::new($path)).GetAccessControl().GetSecurityDescriptorSddlForm([Security.AccessControl.AccessControlSections]::All)
    }
}
[pscustomobject]@{
    result = $result
    before = $before
    after = $after
    journal = $journal
    acl_before = $aclBefore
    acl_after = $aclAfter
    restore = $restore
} | ConvertTo-Json -Depth 40 -Compress
""".replace("SETUP", setup)
        .replace("MODULE", _ps_quote(str(MODULE)))
        .replace("PATCH", patch)
        .replace("AFTER_TRANSACTION", after_transaction)
        .replace("FILES", files),
        encoding="utf-8",
    )
    completed = subprocess.run(
        [shell, "-NoProfile", "-NonInteractive", "-File", str(script)],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def _record(relative: str, new: bytes, old: bytes | None) -> str:
    old_value = "$null" if old is None else _ps_quote(_sha256(old))
    return (
        "[pscustomobject]@{ path = "
        + _ps_quote(relative)
        + "; sha256 = "
        + _ps_quote(_sha256(new))
        + "; expected_old_sha256 = "
        + old_value
        + " }"
    )


def test_applies_in_place_and_preserves_identity_owner_dacl_and_backup(tmp_path: Path) -> None:
    old = b"this is a deliberately longer old reply\n" * 5
    new = b"short\n"
    setup = """
[IO.File]::WriteAllBytes((Join-Path $target 'long.txt'), [Text.Encoding]::UTF8.GetBytes('OLD'))
[IO.File]::WriteAllBytes((Join-Path $payload 'long.txt'), NEW_BYTES)
""".replace(
        "NEW_BYTES",
        "[Convert]::FromBase64String(" + _ps_quote(__import__('base64').b64encode(new).decode()) + ")",
    )
    # Replace the setup's short fixture with the long bytes without using a host file.
    setup = setup.replace(
        "[Text.Encoding]::UTF8.GetBytes('OLD')",
        "[Convert]::FromBase64String(" + _ps_quote(__import__('base64').b64encode(old).decode()) + ")",
    )
    payload = _record("long.txt", new, old)
    outcome = _run_ps(tmp_path, setup, payload)

    assert outcome["result"]["status"] == "APPLIED"
    assert outcome["result"]["created_paths"] == []
    file_result = outcome["result"]["files"][0]
    assert file_result["identity_before"] == file_result["identity_after"]
    assert file_result["acl_semantics_preserved"] is True
    assert outcome["acl_before"]["long.txt"] == outcome["acl_after"]["long.txt"]
    assert __import__('base64').b64decode(outcome["after"]["long.txt"]) == new
    backup = Path(outcome["result"]["backup_root"])
    assert (backup / "journal.json").is_file()
    manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["files"][0]["sddl"]
    assert (backup / "files" / "0000.content.bin").read_bytes() == old


def test_acl_comparison_preserves_access_rule_order(tmp_path: Path) -> None:
    shell = shutil.which("powershell")
    if shell is None:
        pytest.skip("Windows PowerShell required")
    script = tmp_path / "acl-order.ps1"
    script.write_text(
        "$ErrorActionPreference = 'Stop'\n"
        f"$module = Import-Module {_ps_quote(str(MODULE))} -PassThru\n"
        "& $module {\n"
        "  $allowFirst = ConvertTo-CatalogChatAclSemantic -Sddl 'O:SYG:SYD:(A;;FW;;;WD)(D;;FW;;;WD)'\n"
        "  $denyFirst = ConvertTo-CatalogChatAclSemantic -Sddl 'O:SYG:SYD:(D;;FW;;;WD)(A;;FW;;;WD)'\n"
        "  if ($allowFirst -ceq $denyFirst) { throw 'ACL_ORDER_IGNORED' }\n"
        "}\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        [shell, "-NoProfile", "-NonInteractive", "-File", str(script)],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_explicit_rollback_after_success_restores_existing_and_removes_own_new_file(tmp_path: Path) -> None:
    setup = """
[IO.File]::WriteAllText((Join-Path $target 'first.txt'), 'old')
[IO.File]::WriteAllText((Join-Path $payload 'first.txt'), 'new')
[IO.File]::WriteAllText((Join-Path $payload 'new.txt'), 'created')
"""
    result = _run_ps(
        tmp_path, setup,
        ",\n".join([_record("first.txt", b"new", b"old"), _record("new.txt", b"created", None)]),
        after_transaction="$restore = Undo-CatalogChatContentTransaction -TargetRoot $target -Transaction $result -Cause 'POSTINSTALL_CHECK_FAILED'",
    )
    assert result["result"]["status"] == "APPLIED"
    assert result["restore"]["status"] == "ROLLED_BACK"
    assert result["after"] == result["before"]
    assert result["acl_before"] == result["acl_after"]
    journal = json.loads(Path(result["restore"]["journal_path"]).read_text(encoding="utf-8"))
    assert journal["cause"] == "POSTINSTALL_CHECK_FAILED"
    assert journal["status"] == "ROLLED_BACK"


def test_explicit_rollback_rejects_changed_file_before_restoring_anything(tmp_path: Path) -> None:
    setup = """
[IO.File]::WriteAllText((Join-Path $target 'first.txt'), 'old1')
[IO.File]::WriteAllText((Join-Path $target 'second.txt'), 'old2')
[IO.File]::WriteAllText((Join-Path $payload 'first.txt'), 'new1')
[IO.File]::WriteAllText((Join-Path $payload 'second.txt'), 'new2')
"""
    result = _run_ps(
        tmp_path, setup,
        ",\n".join([_record("first.txt", b"new1", b"old1"), _record("second.txt", b"new2", b"old2")]),
        after_transaction="""
[IO.File]::WriteAllText((Join-Path $target 'second.txt'), 'changed')
$restore = Undo-CatalogChatContentTransaction -TargetRoot $target -Transaction $result -Cause 'POSTINSTALL_CHECK_FAILED'
""",
    )
    assert result["restore"]["status"] == "BLOCKED"
    assert result["restore"]["cause"] == "ROLLBACK_CURRENT_HASH_MISMATCH"
    assert __import__('base64').b64decode(result["after"]["first.txt"]) == b"new1"
    assert __import__('base64').b64decode(result["after"]["second.txt"]) == b"changed"


def test_rollback_result_journal_failure_preserves_cause_and_actual_outcome(tmp_path: Path) -> None:
    result = _run_ps(
        tmp_path,
        """
[IO.File]::WriteAllText((Join-Path $target 'first.txt'), 'old')
[IO.File]::WriteAllText((Join-Path $payload 'first.txt'), 'new')
""",
        _record("first.txt", b"new", b"old"),
        patch="""
& $module {
    $script:realDurableJson = ${function:Write-CatalogChatDurableJson}
    function script:Write-CatalogChatDurableJson {
        param([string]$Path, $Value, [IO.FileMode]$Mode)
        if ($Path.EndsWith('post-apply-rollback.result.json')) {
            [IO.File]::WriteAllText($Path, 'partial')
            throw 'TEST_RESULT_JOURNAL_FAILURE'
        }
        & $script:realDurableJson @PSBoundParameters
    }
}
""",
        after_transaction="$restore = Undo-CatalogChatContentTransaction -TargetRoot $target -Transaction $result -Cause 'POSTINSTALL_CHECK_FAILED'",
    )
    assert result["restore"]["status"] == "BLOCKED"
    assert result["restore"]["cause"] == "TEST_RESULT_JOURNAL_FAILURE"
    assert result["restore"]["rollback"]["status"] == "ROLLED_BACK"
    assert result["after"] == result["before"]
    journal = json.loads(Path(result["restore"]["journal_path"]).read_text(encoding="utf-8"))
    assert journal["cause"] == "POSTINSTALL_CHECK_FAILED"
    assert journal["status"] == "ROLLBACK_PENDING"


def test_wrong_old_hash_blocks_before_any_file_is_touched(tmp_path: Path) -> None:
    first_old, first_new = b"first-old", b"first-new"
    second_old, second_new = b"second-old", b"second-new"
    setup = """
[IO.File]::WriteAllBytes((Join-Path $target 'first.txt'), FIRST_OLD)
[IO.File]::WriteAllBytes((Join-Path $target 'second.txt'), SECOND_OLD)
[IO.File]::WriteAllBytes((Join-Path $payload 'first.txt'), FIRST_NEW)
[IO.File]::WriteAllBytes((Join-Path $payload 'second.txt'), SECOND_NEW)
"""
    setup = (
        setup.replace("FIRST_OLD", "[Text.Encoding]::UTF8.GetBytes(" + _ps_quote(first_old.decode()) + ")")
        .replace("SECOND_OLD", "[Text.Encoding]::UTF8.GetBytes(" + _ps_quote(second_old.decode()) + ")")
        .replace("FIRST_NEW", "[Text.Encoding]::UTF8.GetBytes(" + _ps_quote(first_new.decode()) + ")")
        .replace("SECOND_NEW", "[Text.Encoding]::UTF8.GetBytes(" + _ps_quote(second_new.decode()) + ")")
    )
    records = ",\n".join(
        [
            _record("first.txt", first_new, first_old),
            "[pscustomobject]@{ path = 'second.txt'; sha256 = '" + _sha256(second_new) + "'; expected_old_sha256 = '" + "0" * 64 + "' }",
        ]
    )
    outcome = _run_ps(tmp_path, setup, records)

    assert outcome["result"]["status"] == "BLOCKED"
    assert outcome["result"]["cause"] == "OLD_HASH_MISMATCH"
    assert __import__('base64').b64decode(outcome["after"]["first.txt"]) == first_old
    assert __import__('base64').b64decode(outcome["after"]["second.txt"]) == second_old
    assert not (tmp_path / "backup").exists()


def test_path_escape_is_blocked(tmp_path: Path) -> None:
    outside = tmp_path / "outside.txt"
    setup = "[IO.File]::WriteAllBytes((Join-Path $payload 'x.txt'), [Text.Encoding]::UTF8.GetBytes('x'))"
    record = _record("..\\outside.txt", b"x", None)
    outcome = _run_ps(tmp_path, setup, record)

    assert outcome["result"]["status"] == "BLOCKED"
    assert outcome["result"]["cause"] == "PATH_TRAVERSAL"
    assert not outside.exists()


def test_hardlink_is_blocked(tmp_path: Path) -> None:
    setup = """
$real = Join-Path $target 'real.bin'
[IO.File]::WriteAllBytes($real, [Text.Encoding]::UTF8.GetBytes('old'))
New-Item -ItemType HardLink -Path (Join-Path $target 'first.txt') -Target $real | Out-Null
[IO.File]::WriteAllBytes((Join-Path $payload 'first.txt'), [Text.Encoding]::UTF8.GetBytes('new'))
"""
    outcome = _run_ps(tmp_path, setup, _record("first.txt", b"new", b"old"))

    assert outcome["result"]["status"] == "BLOCKED"
    assert outcome["result"]["cause"] == "HARDLINK_REJECTED"
    assert (tmp_path / "target" / "real.bin").read_bytes() == b"old"


def test_existing_backup_root_is_rejected_without_overwrite(tmp_path: Path) -> None:
    setup = """
[IO.File]::WriteAllBytes((Join-Path $target 'first.txt'), [Text.Encoding]::UTF8.GetBytes('old'))
[IO.File]::WriteAllBytes((Join-Path $payload 'first.txt'), [Text.Encoding]::UTF8.GetBytes('new'))
New-Item -ItemType Directory -Path $backup | Out-Null
[IO.File]::WriteAllText((Join-Path $backup 'sentinel.txt'), 'keep')
"""
    outcome = _run_ps(tmp_path, setup, _record("first.txt", b"new", b"old"))

    assert outcome["result"]["status"] == "BLOCKED"
    assert outcome["result"]["cause"] == "BACKUP_ROOT_EXISTS"
    assert (tmp_path / "backup" / "sentinel.txt").read_text() == "keep"
    assert (tmp_path / "target" / "first.txt").read_bytes() == b"old"


def test_second_file_failure_rolls_back_first_and_preserves_original_cause(tmp_path: Path) -> None:
    setup = """
[IO.File]::WriteAllBytes((Join-Path $target 'first.txt'), [Text.Encoding]::UTF8.GetBytes('first-old'))
[IO.File]::WriteAllBytes((Join-Path $target 'second.txt'), [Text.Encoding]::UTF8.GetBytes('second-old'))
[IO.File]::WriteAllBytes((Join-Path $payload 'first.txt'), [Text.Encoding]::UTF8.GetBytes('first-new'))
[IO.File]::WriteAllBytes((Join-Path $payload 'second.txt'), [Text.Encoding]::UTF8.GetBytes('second-new'))
"""
    patch = """
& $module {
    $script:real_writer = (Get-Item Function:\\Write-CatalogChatBytesInPlace).ScriptBlock
    Set-Item Function:\\Write-CatalogChatBytesInPlace -Value {
        param([IO.FileStream]$Stream, [byte[]]$Bytes, [string]$Path)
        if ($Path.EndsWith('second.txt', [StringComparison]::OrdinalIgnoreCase)) {
            throw 'TEST_SECOND_IO_FAILURE'
        }
        & $script:real_writer -Stream $Stream -Bytes $Bytes -Path $Path
    }
}
"""
    records = ",\n".join([_record("first.txt", b"first-new", b"first-old"), _record("second.txt", b"second-new", b"second-old")])
    outcome = _run_ps(tmp_path, setup, records, patch=patch)

    assert outcome["result"]["status"] == "BLOCKED"
    assert outcome["result"]["cause"] == "TEST_SECOND_IO_FAILURE"
    assert outcome["result"]["rollback"]["status"] == "ROLLED_BACK"
    assert outcome["result"]["rollback"]["error"] is None
    assert outcome["journal"]["cause"] == "TEST_SECOND_IO_FAILURE"
    assert outcome["journal"]["rollback"]["status"] == "ROLLED_BACK"
    assert __import__('base64').b64decode(outcome["after"]["first.txt"]) == b"first-old"
    assert __import__('base64').b64decode(outcome["after"]["second.txt"]) == b"second-old"


def test_new_file_is_deleted_on_controlled_later_failure(tmp_path: Path) -> None:
    setup = """
[IO.File]::WriteAllBytes((Join-Path $target 'first.txt'), [Text.Encoding]::UTF8.GetBytes('first-old'))
[IO.File]::WriteAllBytes((Join-Path $target 'third.txt'), [Text.Encoding]::UTF8.GetBytes('third-old'))
[IO.File]::WriteAllBytes((Join-Path $payload 'first.txt'), [Text.Encoding]::UTF8.GetBytes('first-new'))
[IO.File]::WriteAllBytes((Join-Path $payload 'new.txt'), [Text.Encoding]::UTF8.GetBytes('new-content'))
[IO.File]::WriteAllBytes((Join-Path $payload 'third.txt'), [Text.Encoding]::UTF8.GetBytes('third-new'))
"""
    patch = """
& $module {
    $script:real_writer = (Get-Item Function:\\Write-CatalogChatBytesInPlace).ScriptBlock
    Set-Item Function:\\Write-CatalogChatBytesInPlace -Value {
        param([IO.FileStream]$Stream, [byte[]]$Bytes, [string]$Path)
        if ($Path.EndsWith('third.txt', [StringComparison]::OrdinalIgnoreCase)) {
            throw 'TEST_THIRD_IO_FAILURE'
        }
        & $script:real_writer -Stream $Stream -Bytes $Bytes -Path $Path
    }
}
"""
    records = ",\n".join(
        [
            _record("first.txt", b"first-new", b"first-old"),
            _record("new.txt", b"new-content", None),
            _record("third.txt", b"third-new", b"third-old"),
        ]
    )
    outcome = _run_ps(tmp_path, setup, records, patch=patch)

    assert outcome["result"]["status"] == "BLOCKED"
    assert outcome["result"]["cause"] == "TEST_THIRD_IO_FAILURE"
    assert outcome["result"]["created_paths"] == ["new.txt"]
    assert outcome["result"]["rollback"]["deleted_created_paths"] == ["new.txt"]
    assert not (tmp_path / "target" / "new.txt").exists()
    assert (tmp_path / "target" / "first.txt").read_bytes() == b"first-old"
    assert (tmp_path / "target" / "third.txt").read_bytes() == b"third-old"
