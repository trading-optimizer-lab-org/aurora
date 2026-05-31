# Daily Ops Report Delivery Recipe (R37)

`forge ops daily` and `forge ops alerts` produce the operational
report. This doc covers wiring delivery (Slack, email), cadence, and
notification hygiene so operators don't drown in alerts.

## Outputs

`forge ops daily` writes:

- A markdown report under `$QF_DATA_DIR/daily_ops/<date>.md`.
- A JSON sidecar with the same content for downstream tools.
- Six categorised alert checks: drawdown breach, kill-switch state,
  data freshness, regime change, drift detection, validation marker
  staleness.

`forge ops alerts` filters the JSON sidecar and emits only the alerts
above a configurable severity.

## Slack

```bash
# Set the webhook once in your secrets manager.
export QFORGE_SLACK_WEBHOOK="https://hooks.slack.com/services/..."

forge ops alerts \
  --severity warn \
  --slack-webhook "$QFORGE_SLACK_WEBHOOK"
```

Recommended:

- One Slack channel for alerts (`#aurora-ops`).
- Severity gate at `warn` in working hours, `error` overnight.
- Use Slack workflow rate-limit (max 5/min per webhook).

## Email

```bash
export QFORGE_SMTP_HOST="smtp.example.com"
export QFORGE_SMTP_USER="[email protected]"
export QFORGE_SMTP_PASSWORD="$(vault kv get -field=password secret/aurora/smtp)"

forge ops alerts \
  --severity error \
  --email "[email protected]"
```

Email is the right channel for daily summaries and high-severity
escalations. Slack is the right channel for real-time alerts.

## Cron / scheduler cadence

- `forge ops daily` once per day at session close (e.g. 21:00 UTC for
  US strategies).
- `forge ops alerts --severity warn` every 15 minutes during market
  hours.
- `forge ops alerts --severity error` every minute, always.
- Weekly summary: cron Sunday 09:00 UTC.

## Notification fatigue mitigations

1. **Severity gating**. WARN is for review; ERROR is for action.
2. **Per-rule cooldown**. Built into `monitoring/alerts.py`: each
   rule fires at most once per cooldown window (default 1h).
3. **Aggregation**. Multiple WARN events within a cooldown are
   bundled into a single message.
4. **Quiet hours**. Configure operator-side quiet hours in your
   notification platform; Aurora does not silence them itself
   because silenced operations are a security smell.
5. **Channel split**. Day vs night, dev vs prod, paper vs live.

## Verification

After wiring, run a dry-fit:

```bash
forge ops alerts --dry-run --slack-webhook ...
```

Dry-run prints the message that would have been sent without
hitting the network.

## Out of scope

- PagerDuty integration: configure operator-side, the alerts arrive
  via the existing Slack channel.
- Statuspage updates: same.
- Mobile push: see roadmap R122 (multi-channel alerts).
