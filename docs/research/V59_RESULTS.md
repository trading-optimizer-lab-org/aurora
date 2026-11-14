# v59 results: v58's book with the night short limited to bigger opening gaps

Run 43586006131 (2026-11-14), pre-registered in V59_PREREGISTRATION.md. Book DS0.20-NS0.60-RU0.25-N5.

- Check: no gap filter in W0 gave $13,041 and 1.0% ruin: reproduced. G30 equals the control (every NS pick
  already needs a 30% gap).
- **No G beats the control**: each step up in G lowers the median in every world and lowers ruin a little.

| NS gap at least | NS candidates | W0 | F0C1 (central) | F1C1 | HOT5 ruin W0 | 2023+ W0 |
|---|---|---|---|---|---|---|
| none / 30% | 315 | $13,041 / 1.0% | $11,634 / 1.1% | $11,269 / 0.9% | 1.0% | $11,645 / 1.4% |
| 50% | 215 | $12,759 / 0.9% | $11,404 / 1.0% | $11,006 / 0.8% | 1.0% | $11,845 / 1.2% |
| 75% | 147 | $12,293 / 0.9% | $11,197 / 0.9% | $10,886 / 0.8% | 0.9% | $12,273 / 1.1% |
| 100% | 107 | $11,966 / 0.8% | $10,766 / 0.9% | $10,583 / 0.7% | 0.8% | $12,378 / 1.0% |
| 150% | 61 | $11,128 / 0.4% | $10,138 / 0.5% | $10,116 / 0.5% | 0.4% | $10,763 / 1.0% |

Reading: the 30-50% gaps add money on the full sample. Since 2023 the bigger gaps do slightly better (G100
+6% median, ruin 1.4% -> 1.0%), a hint only: six values on one book, chosen after seeing the data. NS size was
held at 0.60, so the filtered books also run with less capital at work; a larger NS size on fewer, bigger gaps
was not tested.
