# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| 1.4.x   | yes (current)      |
| 1.3.x   | security fixes only |
| < 1.3   | no                 |

## Reporting a Vulnerability

**Do not open public GitHub issues for security vulnerabilities.**

Email the maintainer directly with:

- A description of the vulnerability.
- Reproduction steps or proof of concept.
- The affected version and environment.
- Suggested fix or mitigation, if you have one.

You should expect an initial acknowledgement within **5 business days**
and a status update within **30 days**. Critical issues affecting live
trading paths or audit-chain integrity will be triaged on a shorter
window.

## Disclosure Window

We follow a coordinated-disclosure model:

- We aim to ship a patched release within **90 days** of confirmed
  critical reports.
- We will publish an advisory on the affected versions and a CVE
  reference if applicable.
- We credit reporters who request public credit.

## Out of Scope

The following are NOT security vulnerabilities for the purposes of this
policy:

- Best-practice deviations that do not enable an attack.
- Reports against modules under `experimental/` (see roadmap R48).
- Reports requiring physical access to the operator machine.
- Reports against third-party data vendors (forward to the vendor).
- Issues in test-only fixtures or demo strategies.

## Security-Sensitive Surfaces

Reviewers and reporters should give extra attention to:

- `agent_gateway/` -- token signing, stage / commit / push pipeline,
  hash-chained audit trail.
- `core/data_layer.py` and `core/data_tiers.py` -- OOSGuard, tier
  ceremonies.
- `compliance/encryption_at_rest.py`, `compliance/pii_handler.py`,
  `compliance/two_factor.py`, `compliance/rbac.py`.
- `deployment/live.py` and broker adapters -- triple-gate enforcement,
  kill switch, rate limiter.
- `core/protocol_policy.py` -- policy hash propagation.
- Environment-variable handling for secrets (see roadmap R57).

## Hardening Status

Active hardening tracked in
[`docs/roadmap/ROADMAP_PENDING.md`](docs/roadmap/ROADMAP_PENDING.md):

- R34 audit-log rotation policy.
- R35 HMAC key generation and rotation operator guide.
- R36 disaster recovery and snapshot restore.
- R43 multi-user / RBAC for the agent gateway.
- R44 strategy spec verification chain.
- R57 centralised env-var inventory.
- R61 CI security scanning (bandit, pip-audit).
- R69 (this document).
- R71 concurrent strategy run isolation.
- R153 sealed-envelope forecast ceremony.

## Acknowledgements

Will list confirmed reporters once disclosures land.
