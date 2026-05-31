# Disaster Recovery (R36)

What to do when the snapshot store, audit chain or research archive is
in a degraded state.

## Inventory of recoverable artefacts

| Artefact | Default location | Recovery primitive |
|---|---|---|
| Snapshot blobs | `$QF_SNAPSHOT_ROOT/blobs/<sha256>.parquet` | `forge data repair` (R36 helper) |
| Snapshot index | `$QF_SNAPSHOT_ROOT/snapshots_index.sqlite` | rebuild from blobs |
| SOC2 audit trail | `$QF_AUDIT_LOG` | hash-chain replay verifier |
| Gateway audit chain | `$QF_GATEWAY_AUDIT` | `forge agent audit-verify` |
| Research archive | `$QF_RESEARCH_ARCHIVE` | re-import from review queue + reports |
| Review queue | `$QF_REVIEW_QUEUE` | re-derive from factory submissions |
| Trade journal | `$QF_JOURNAL` | hash-chain replay |
| Validation markers | `<project>/.qf_cache/.validation_passed_*.json` | re-run validation pipeline |

## Snapshot store recovery

### Symptom: corrupted SQLite index

```bash
sqlite3 "$QF_SNAPSHOT_ROOT/snapshots_index.sqlite" "PRAGMA integrity_check;"
# returns errors
```

Recovery procedure:

1. Move the broken index aside:
   ```bash
   mv "$QF_SNAPSHOT_ROOT/snapshots_index.sqlite" \
      "$QF_SNAPSHOT_ROOT/snapshots_index.sqlite.broken-$(date +%s)"
   ```
2. Rebuild the index from the blob filenames:
   ```bash
   python -m aurora.core.snapshot_repair --root "$QF_SNAPSHOT_ROOT"
   ```
   The repair walker reads every parquet under `<root>/blobs/`,
   re-hashes the contents, and re-inserts a row only when
   `sha256(content) == filename_stem`. Mismatches are skipped and
   listed.
3. Verify the rebuilt index resolves an expected snapshot:
   ```bash
   forge data verify --snapshot-id <known-id>
   ```

### Symptom: blob hash mismatch

A parquet on disk no longer matches the sha256 it was filed under.
Cause is usually disk rot or interrupted write.

```bash
python -m aurora.core.snapshot_repair --check-only --root "$QF_SNAPSHOT_ROOT"
```

Output lists every mismatched blob. Decisions:

- If you have a backup, restore the blob from backup and re-verify.
- If no backup, delete the blob and re-fetch from the original
  provider (`forge data fetch`) under the original ceremony.
- Tampering: if the blob hash changed without operator action,
  treat as a security incident (see SECURITY.md).

### Symptom: missing `policy_hash`

A snapshot row's `policy_hash` is null, or does not match any known
historical `ProtocolPolicy`. Likely caused by a partially-migrated
older release.

Recovery: snapshots without a verifiable `policy_hash` MUST be
quarantined. They cannot be used for promotion since the protocol
they were captured under is unknown.

## Audit chain recovery

### Symptom: hash chain breaks

```bash
forge agent audit-verify
# ERROR: chain break at index 142, expected hash X, got hash Y
```

Causes:

1. A line was edited, deleted, or reordered (treat as security
   incident).
2. A rotation boundary is missing its `rotation_anchor` record.
3. A writer crashed mid-line (last line partial).

Recovery for case 3 (partial last line):

1. Snapshot the file:
   `cp "$QF_GATEWAY_AUDIT" "$QF_GATEWAY_AUDIT.recovery-$(date +%s)"`.
2. Drop the partial last line.
3. Re-run `forge agent audit-verify`.
4. If it passes, you can resume.

Recovery for case 1 / 2: do NOT silently patch. The chain's purpose is
to make tampering detectable. Open an incident, document, and decide
whether to invalidate downstream artefacts that referenced the broken
chain.

## Research archive recovery

The research factory writes archive + review-queue JSONL files. If
either file is corrupted:

1. Restore from backup if available.
2. Otherwise, re-import from the per-strategy `auditor_report_hash`
   stored in each `CandidateRun.to_dict()` row that survived. The
   audit reports themselves are stored alongside snapshots, so the
   full chain can be reconstructed even after archive loss, just
   slowly.

R9 (`research/rag.py`) tolerates malformed JSONL rows by skipping
them; the index keeps working with the remaining rows. Use that as
the read path while the archive is being repaired.

## Validation marker recovery

Validation markers are intentionally cheap to lose: they are derived
state. If you lose them, re-run the validation pipeline:

```bash
forge validate --strategy <name> --asset <symbol>
```

A fresh validation regenerates the marker. The previous run remains
in the audit trail; the marker just confirms the pipeline saw the
strategy and the policy at a recent date.

## Backup strategy

Aurora does not ship a backup tool. The recommended pattern:

1. Daily: rsync `$QF_DATA_DIR` to a separate disk or object store.
2. Weekly: cold backup (offline copy) of the snapshot blobs and the
   audit logs. Cold means "not reachable from the production
   machine" -- a malware incident on the production box must not
   reach the cold backup.
3. Quarterly: integrity check (`forge data verify` + audit-verify)
   on the cold backup. Storage that you never read from is storage
   that does not exist.

## Out of scope

- Recovering keys lost from the secrets manager. See
  `docs/HMAC_KEY_OPERATIONS.md`.
- Recovering compromised broker credentials. Rotate at the broker,
  not in Aurora.
- Reconstructing in-flight live orders from a partially crashed
  process. The KillSwitch should fire on detect-and-pause; broker
  reconciliation is the canonical truth, not the local audit log.
