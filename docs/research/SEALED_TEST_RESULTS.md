# The sealed test: results

GitHub run 39418639505 (2026-10-20), opened once at the owner's request, as fixed in
[SEALED_TEST_PROTOCOL.md](SEALED_TEST_PROTOCOL.md); the finalists were frozen on design data in run 39418288599
and committed before the window was opened ([data/sealed_frozen.json](data/sealed_frozen.json)).

## Verdict: failure

| strategy | Sortino 2023-07 to 2026-10 (middle costs) | CAGR | max DD | spreads x2 | design 2018-2023H1 (same frozen choice) |
|---|---|---|---|---|---|
| COMBO16 | **0.46** | 6.5% | -10.9% | -1.22 | 10.93 |
| S1 (no-news gap fade, gap >= 50%) | **1.27** | 11.3% | -12.2% | 0.13 | 8.15 |
| B8R1 (gap fade, IBKR availability) | **0.28** | 6.1% | -20.0% | -1.34 | 5.15 |

- The pre-registered threshold was 4 for success and 3 for promising; all three are below 3.
- The design column uses the same frozen choice, which saw all design data, so it is in-sample; the drop from
  8-11 to 0.3-1.3 is the measure of how much of v16 was fitted to 2016-2023 or to that period's conditions.
- S1 stayed positive every year (+8.3% in 2023H2, +16.9% in 2024, +6.0% in 2025, +5.9% in 2026 to October), but
  with a Sortino of 1.27 it is about what an index fund gives, and with spreads x2 it is flat.
- The effect behind v16 (shorting small-cap gap-ups that break the 5-minute low) has been much weaker since mid-2023
  than in 2018-2023 (S1 made +12% to +26% a year then). Why is not known from this test: more traders fading
  these gaps, different market conditions, or a design period that flattered it.
- The window is now spent for these families: nothing will be re-selected on it.

## Full report

Frozen on design data only (docs/research/data/sealed_frozen.json); protocol in docs/research/SEALED_TEST_PROTOCOL.md.

| strategy | costs | Sortino sealed | CAGR | max DD | total | design Sortino (2018-2023H1) | by year |
|---|---|---|---|---|---|---|---|
| COMBO16 | mid | 0.46 | 6.5% | -10.9% | +23% | 10.93 | 2023 +3.5%, 2024 +15.8%, 2025 -0.1%, 2026 +2.6% |
| COMBO16 | high | -1.22 | -2.1% | -17.0% | -7% | 5.83 | 2023 +1.4%, 2024 +7.1%, 2025 -7.9%, 2026 -6.6% |
| S1 | mid | 1.27 | 11.3% | -12.2% | +42% | 8.15 | 2023 +8.3%, 2024 +16.9%, 2025 +6.0%, 2026 +5.9% |
| S1 | high | 0.13 | 4.9% | -17.8% | +17% | 5.69 | 2023 +6.3%, 2024 +11.2%, 2025 -1.0%, 2026 +0.0% |
| B8R1 | mid | 0.28 | 6.1% | -20.0% | +21% | 5.15 | 2023 +1.3%, 2024 +22.3%, 2025 -4.8%, 2026 +3.0% |
| B8R1 | high | -1.34 | -10.3% | -37.1% | -30% | 1.59 | 2023 -4.0%, 2024 +5.7%, 2025 -20.9%, 2026 -13.0% |

Verdict (middle costs): COMBO16: failure, S1: failure, B8R1: failure

COMBO16 weights: B11 5%, B12 3%, D23 4%, D25 11%, B8R1 9%, AH2 9%, S1 16%, S2 23%, S3 21%
