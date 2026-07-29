# GTBI V7 Provider-Terms Review Candidate

Observed: `2026-07-29T14:41:25Z`

Status: `BLOCKED_PENDING_INDEPENDENT_REVIEW`

This is a technical inventory and risk classification, not legal advice and
not the independent licence-review receipt required by the master plan.

## GitHub

The current official terms, additional-product terms and Actions billing
documentation are recorded byte-for-byte by URL and SHA-256 in
`provider_terms_inventory.json`.

The relevant operational conclusions are:

- standard GitHub-hosted runners in public repositories currently have no
  metered compute charge;
- private repository compute and storage can become billable;
- GitHub Actions use must remain related to development, testing, deployment
  or publication of the repository software;
- disproportionate server burden is restricted;
- the planned maximum workload still needs independent acceptable-use review
  and, where ambiguity remains, written confirmation from GitHub Support;
- the owner's `0 USD` incremental-spend cap forbids any new billable topology.

Sources:

- https://docs.github.com/en/site-policy/github-terms/github-terms-of-service
- https://docs.github.com/en/site-policy/github-terms/github-terms-for-additional-products-and-features
- https://docs.github.com/en/billing/concepts/product-billing/github-actions

## Yahoo Finance And `yfinance`

The current Yahoo terms restrict automated collection without express prior
permission. The repository has no evidence of that permission.

The Apache-2.0 licence for `yfinance` permits use of the client code. It does
not grant rights to Yahoo market data or override Yahoo's service terms.

Therefore:

- owner acceptance is recorded, but cannot create a permission the provider
  has not granted;
- the existing Yahoo-derived data lake may be preserved as historical
  evidence, but it is not an approved V7 scientific input;
- no V7 full run may use it until an independent reviewer accepts documented
  provider permission or the data source is replaced with one whose terms
  permit the exact use, retention and redistribution model.

Sources:

- https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html
- https://github.com/ranaroussi/yfinance/blob/main/LICENSE.txt
