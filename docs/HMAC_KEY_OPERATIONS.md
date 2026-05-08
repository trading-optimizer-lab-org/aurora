# HMAC Key Operations (R35)

Operator-facing guide for the HMAC keys QuantForge uses to sign agent
tokens, operator countersignatures, and audit-trail records.

## Keys at a glance

| Env var | What it signs | Required for | Rotation cadence |
|---|---|---|---|
| `QF_GATEWAY_SECRET` | `AgentToken` payloads issued by the gateway | Any agent flow that calls `issue_token` or `stage / commit / push` | 90 days, or immediately on suspected compromise |
| `QF_OPERATOR_KEY` | Operator counter-signature for a `StagedAction` | Live trades and any commit policy where `require_human_commit_for_live=True` | 90 days |
| `QF_PII_FERNET_KEY` | At-rest PII encryption | `compliance/pii_handler.py` writes | 180 days |
| `QF_PII_HMAC_KEY` | Deterministic PII masking pepper | Same as above | 180 days |
| `QF_TOTP_SECRET` | Two-factor login seed | `compliance/two_factor.py` | Per operator, on device change |
| `QF_SQLCIPHER_KEY` | Audit DB encryption | When SQLCipher backend is enabled | 180 days |

## Generation

All keys are 32+ random bytes encoded as hex. A trivial generator:

```python
import secrets

print(secrets.token_hex(32))   # 64-char hex string, 256 bits of entropy
```

For Fernet specifically:

```python
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
```

For the TOTP secret, follow the standard RFC 6238 base32 format your
authenticator app expects; do **not** reuse `token_hex` output.

## Storage

- **Never** in the repository.
- **Never** in a `.env` file committed to any branch.
- **Never** echoed by any logger. The auditor and gateway log the
  *token id* (`token_id`), not the secret, by design.

Operator-grade options, in order of preference:

1. A real secret manager: HashiCorp Vault, AWS Secrets Manager, GCP
   Secret Manager, Azure Key Vault.
2. A team password manager that supports machine-readable export: 1Password
   Connect, Bitwarden Vault.
3. As a last resort for a single-operator workstation: an encrypted
   `.env` outside the repo (e.g. `~/.aurora/secrets.env`) loaded into
   the shell with `direnv`. This is acceptable for personal-use mode
   only.

## Loading at runtime

QuantForge reads each variable lazily on the first use; if the variable
is missing the gateway / pipeline raises a typed `RuntimeError` rather
than silently signing with empty bytes. The expected pattern is:

```bash
# Pull from the secrets manager into the current shell.
export QF_GATEWAY_SECRET="$(vault kv get -field=secret secret/aurora/gateway)"
export QF_OPERATOR_KEY="$(vault kv get -field=key secret/aurora/operator)"

# Now run the gateway / agent / live wrappers.
python -m quantforge.cli.forge agent stage --strategy MACross ...
```

## Rotation procedure

The chain-of-trust is:

1. New key minted in the secrets manager. Old key kept until step 4.
2. New key bound to **future** tokens / signatures only. Anything
   already in flight (a `StagedAction` that has been staged but not
   pushed) keeps its original signature.
3. Operator drains in-flight staged actions: either commit and push,
   or expire / revoke. The gateway exposes
   `forge agent stage-list / stage-revoke` for this.
4. Old key removed from the secrets manager. Audit trail records
   `key_id_old` and `key_id_new` so a verifier can correlate which
   records used which key.

If you rotate without draining first, in-flight signatures fail the
HMAC check and the gateway refuses them. That is the intended
outcome -- it makes a key swap impossible to do silently mid-session.

### Cadence

- 90 days for `QF_GATEWAY_SECRET` and `QF_OPERATOR_KEY`.
- 180 days for the PII / DB encryption keys.
- Immediately on suspected compromise (push a leak alert, drain
  in-flight actions, rotate, re-issue).

## Recovery if a key is lost

A lost `QF_GATEWAY_SECRET` invalidates **every** token currently in
issue. There is no recovery; you must:

1. Mint a fresh secret.
2. Re-issue every active token with the fresh secret.
3. Notify every actor (LLM agent, cron job) of the new token.
4. Do **not** import old token records into the new chain.

A lost `QF_OPERATOR_KEY` invalidates pending operator commits but does
**not** invalidate executed orders -- those are already in the audit
chain by `committed_id`.

## Recovery if a key is exposed

Treat as an active incident:

1. Rotate immediately, draining if possible. If draining is not
   possible, accept that pending in-flight tokens are now invalid.
2. Audit the exposure window: `forge agent audit-verify` plus a manual
   sweep of `gateway_audit.jsonl` for actor / scope combinations that
   should not have been issued.
3. Walk every order placed in the exposure window and decide whether
   reconciliation or reversal is required.
4. Document the incident in `CHANGELOG.md` and the audit trail.

## Verification

Two on-demand checks should be part of every key rotation:

```bash
# Verify the gateway audit chain is internally consistent.
forge agent audit-verify

# Verify ProtocolPolicy hash matches the active policy file.
forge policy verify
```

Both should exit 0. A non-zero exit means the chain has a discontinuity
the rotation introduced -- investigate before continuing.

## Test fixtures

Tests must NEVER reuse production secrets. The pattern across the test
suite is:

```python
monkeypatch.setenv("QF_GATEWAY_SECRET", "test-secret-for-this-test-only")
```

The `_gateway_secret` fixture in `tests/test_protocol_fuzz.py` shows the
canonical setup. Production-style values must come from `secrets.token_hex`
in CI, never a literal string.
