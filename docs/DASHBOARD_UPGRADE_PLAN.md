# Dashboard Upgrade Plan (R85)

## Status

Plan + minimal data-source surface. The Streamlit app at
`monitoring/dashboard.py` stays as the deployment target; the
upgrade lands as a series of additive panels, each one fed by an
existing in-repo data source. No new dependencies.

## Why this is plan-first

The current dashboard is functional. A "rip-and-replace" pass risks
breaking the operator workflow that already runs daily. The pragmatic
shape: keep the existing entry point, add panels one at a time, each
panel is a separate function under `monitoring/panels/` so it is
unit-testable in isolation.

This document records the panel inventory + acceptance criteria so
the per-panel PRs stay focused. The actual rendering code lands per
panel; the planning artefact is this file.

## Panel inventory

### Live equity panel

- Source: `agent_gateway.audit` log (per-strategy fills) + the
  cumulative PnL helper from `analytics/`.
- Acceptance: equity curve per strategy, drawdown overlay, last-bar
  marker.

### Real-time PnL strip

- Source: live broker connection (`deployment/brokers.py::PaperBroker`
  / `LiveBroker`).
- Acceptance: cash + position MV + total NAV per strategy + portfolio
  total.

### Live alerts feed

- Source: `monitoring/multi_channel_alerts.py` queue.
- Acceptance: rolling last-100 alerts with severity badge and
  acknowledge button.

### Kill-switch state

- Source: `agent_gateway.kill_switch`.
- Acceptance: clear ON/OFF visual + last-actor + reason.

### Audit-trail tail

- Source: `agent_gateway.audit::AgentAudit.entries()`.
- Acceptance: last 100 entries with hash-chain validity badge.

### Broker connection health

- Source: per-broker adapter ``health_check()`` (where present;
  see R4 follow-up for adapters that need one).
- Acceptance: green / yellow / red per adapter.

### Position concentration

- Source: deployment/position view + per-symbol weight aggregation.
- Acceptance: top-10 names by absolute weight; warn when any name >
  threshold (operator-configured).

### "What no-trade reason fired today" panel

- Source: `reporting/daily_ops/builder.py` no-trade-reason aggregator.
- Acceptance: counts per reason for the trailing day, with click-
  through to the audit entry that fired the reason.

## Out of scope

- Rebuilding in a non-Streamlit framework. If a future contributor
  wants Plotly Dash / Solara / FastHTML, that lands as a separate
  proposal; this upgrade keeps Streamlit.
- Authentication / multi-user views. RBAC roles (R43) are gateway-
  level; the dashboard inherits whatever the operator's reverse
  proxy enforces.
- Mobile-friendly layout. Desktop-first; mobile is operator-side
  responsibility.

## Per-panel acceptance template

Every panel PR includes:

1. Pure data-source function in `monitoring/panels/<name>.py` that
   returns a ``PanelData`` dict.
2. Streamlit render in the same module that consumes the dict.
3. Unit test under `tests/test_dashboard_<name>.py` exercising the
   data-source function.
4. Screenshot in the PR description (mocked data fine).

## Definition of done

- Every panel above has shipped or has been explicitly descoped.
- The existing `monitoring/dashboard.py` entry point still works and
  loads the new panels.
- Each panel has a unit test + a doc string telling operators which
  data source it reads.

## Roll-out order

The order minimises operator-visible churn:

1. Audit-trail tail (smallest blast radius).
2. Live alerts feed.
3. Kill-switch state.
4. Real-time PnL strip.
5. Live equity panel.
6. Position concentration.
7. Broker connection health.
8. "What no-trade reason fired today" panel.
