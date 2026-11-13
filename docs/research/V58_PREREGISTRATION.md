# v58: v57 on a finer grid of cheaper locate worlds: pre-registration

Written and committed on 2026-11-13, before any v58 number was computed. v57 found the target met only in W0 (no
failures, $0.01 / $0.03 a share) and missed on the median in F1C2 (2% / 10% failures, $0.03 / $0.12). v58 fills
the grid between those two worlds.

## 1. Engine (as v57)

- v57's engine and 48 books unchanged; ETB as the model, since v57 found the E worlds equal to their twins.

## 2. Worlds

- **W0**: v56's W0. Check: DS0.20-NS0.60-RU0.25-N5 must give $13,041 and 1.0% ruin.
- Failures (HTB / HOT): **F0** 1% / 5%, **F1** 2% / 10%.
- Price a share (HTB / HOT): **C0** $0.01 / $0.03 (v56's), **C1** $0.02 / $0.06.
- 2 x 2 = 4 worlds plus W0.

## 3. Selection and decision (as v57)

- Same pick on 2018-2022 paths and same MET rule on 2018-2026 and 2023+ paths.
- Private reading, fixed now: the central world is the grid point nearest the quotes' measured failure rates and
  mean price a share by tier, taken from the 15:50 quotes when they number at least 100, else from all quotes;
  the stress world is v57's F1C2.

## 4. Caveats (as v57)

- Few days of quotes; the reading is redone when the logger has two weeks of 15:50 quotes.
- Failures drawn at random by symbol and day; a mean price a share stands in for a skewed distribution.
