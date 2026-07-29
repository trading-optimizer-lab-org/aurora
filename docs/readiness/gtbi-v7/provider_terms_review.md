# GTBI V7 Provider-Terms Review Candidate

Observed: `2026-07-29T14:41:25Z`

Status: `OWNER_ACCEPTED_WITH_CAPACITY_CONDITION`

This is a technical inventory and owner-approved operating decision, not legal
advice. No independent licence reviewer is required.

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
- no future V7 snapshot will use Yahoo or `yfinance`.

Sources:

- https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html
- https://github.com/ranaroussi/yfinance/blob/main/LICENSE.txt

## Selected Replacement: Tiingo

Aurora already contains the tested `tiingo_daily` provider. V7 selects Tiingo
Starter for internal historical daily research:

- price: `0 USD/month`;
- history advertised: more than 30 years;
- limits: 50 requests/hour, 1000 requests/day, 500 unique symbols/month and
  1 GB/month;
- credential: GitHub secret exposed to the job as `AU_TIINGO_API_TOKEN`;
- approved scope: internal research only.

This removes the Yahoo permission problem, but it does not make the full global
universe instantly downloadable. A complete snapshot requires either a
universe of at most 500 unique symbols, staged collection across months, or a
later owner-approved source/tier that remains within the `0 USD` incremental
spend cap. No scientific run may silently shrink or change the universe.

Sources:

- https://www.tiingo.com/about/terms
- https://www.tiingo.com/about/pricing
- https://www.tiingo.com/documentation/end-of-day
