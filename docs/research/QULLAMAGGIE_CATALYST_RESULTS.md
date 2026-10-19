# Qullamaggie fase 5, EP con catalizador real: resultados

Run de GitHub: [39131901612](https://github.com/trading-optimizer-lab-org/aurora/actions/runs/39131901612)
(intento 2, tras añadir `SEC_USER_AGENT`). Reglas:
[QULLAMAGGIE_CATALYST_PREREGISTRATION.md](QULLAMAGGIE_CATALYST_PREREGISTRATION.md). Sesgo de supervivencia sin
corregir. Periodo bloqueado (2021+) sin leer.

## Comprobaciones y cobertura

- `CAT_ANY_N1_EP` = `I_EP_E0` (fase 2) y `CAT_ANY_N1_MIX` = `I_MIX_MODEL_N3_E0` (fase 3): diferencia 0.
- 3.080 huecos candidatos a EP, todos con datos de la SEC; 728 (24%) coinciden con un 8-K de resultados
  (Item 2.02); 1.931 tienen dato de ventas y 218 son resultados con ventas +25% o más. 1.428 llamadas a la SEC.

## Resumen en español

- **Los EP de resultados son mucho más estables**: mejor PF (1,69-1,73 frente a 1,25-1,40) y más aciertos
  (38-39% frente a 30-33%). `CAT_EARN_N0_EP`: 15,3%/año en 2016-2018 y 15,0% en 2019-2020, caída máxima -8,7%,
  PF 1,73, deflated Sharpe 0,34 (el más alto de esta fase).
- **El gran 2019-2020 de los EP venía de huecos SIN resultados** (noticias, sobre todo 2020): `CAT_NOEARN_N1_EP`
  gana 56%/año en 2019-2020 y pierde -3,7%/año en 2016-2018. Es la parte que depende del momento.
- **El filtro de crecimiento de ventas (+25%) empeora**: deja pocas operaciones (53-97 en EP solo) con PF 0,80-1,33.
  Su regla de "grandes cifras de crecimiento", medida así, no ayuda.
- **El filtro "no había subido" importa menos con resultados**: sin él (`N0`) hay más operaciones con PF parecido.
- **Mezcla con las 3 mejores rupturas**:
  - `CAT_ANY_N1_MIX` (la de siempre): 39,8%/año, +434%, pero 22,7% / 70,1% por tramos.
  - `CAT_EARN_N0_MIX` (solo EP de resultados): 27,2%/año, +233%, Sortino 3,25, caída -17,2%, y más pareja:
    33,1%/año en 2016-2018 (Sortino 4,80) y 18,9% en 2019-2020.
- 11 de las 16 combinaciones pasan los criterios. Deflated Sharpe máximo 0,34: ninguna demostrada.

## Informe completo (generado por el código)

# Qullamaggie phase 5: episodic pivots with a real earnings catalyst (pre-registered, 16 trials)

16 of 16 trials (2016-2020); deflated Sharpe over 249,198 trials. Survivorship bias NOT adjusted. Locked period from 2021-01-01 never read. Columns per period: monthly Sortino | CAGR | max drawdown | total return of the portfolio.

Coverage: 3,080 EP candidate gaps; 3,080 with SEC filings; 728 on an Item 2.02 release; 1,931 with revenue growth; 218 on a release with revenue +25% or more. SEC calls: 1428.

SPY: 2016-2018 1.05 | 9.2% | -19.3% | +30% · 2019-2020 1.87 | 24.6% | -33.7% | +55% · 2016-2020 1.45 | 15.1% | -33.7% | +102%.

## 1. All trials

| trial | 2016-18 Sortino | CAGR | max DD | total | 2019-20 Sortino | CAGR | max DD | total | 2016-20 Sortino | CAGR | max DD | total | trades | win | PF | avg | DSR | passed |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| CAT_ANY_N1_EP | 1.01 | 5.3% | -15.5% | +17% | 8.59 | 65.3% | -14.8% | +174% | 4.72 | 26.2% | -16.8% | +219% | 636 | 33% | 1.40 | +1.97% | 0.18 | YES |
| CAT_ANY_N1_MIX | 2.51 | 22.7% | -18.5% | +84% | 7.40 | 70.1% | -15.2% | +190% | 4.45 | 39.8% | -18.5% | +434% | 946 | 32% | 1.45 | +1.92% | 0.30 | YES |
| CAT_ANY_N0_EP | 1.10 | 7.2% | -16.2% | +23% | 6.77 | 63.5% | -21.0% | +168% | 3.75 | 27.0% | -21.0% | +230% | 954 | 30% | 1.25 | +1.27% | 0.15 | YES |
| CAT_ANY_N0_MIX | 2.54 | 25.5% | -17.9% | +97% | 5.95 | 61.1% | -17.5% | +160% | 3.90 | 38.7% | -25.9% | +413% | 1,245 | 30% | 1.30 | +1.39% | 0.25 | no |
| CAT_EARN_N1_EP | 4.18 | 11.2% | -7.1% | +37% | 1.28 | 6.6% | -6.3% | +14% | 2.51 | 9.3% | -7.1% | +56% | 192 | 39% | 1.69 | +2.20% | 0.13 | no |
| CAT_EARN_N1_MIX | 4.10 | 28.1% | -14.6% | +110% | 1.62 | 13.9% | -11.2% | +30% | 2.88 | 22.2% | -15.3% | +172% | 516 | 34% | 1.61 | +1.86% | 0.12 | YES |
| CAT_EARN_N0_EP | 4.60 | 15.3% | -8.7% | +53% | 2.44 | 15.0% | -8.2% | +32% | 3.29 | 15.2% | -8.7% | +103% | 284 | 38% | 1.73 | +2.31% | 0.34 | YES |
| CAT_EARN_N0_MIX | 4.80 | 33.1% | -14.9% | +135% | 1.93 | 18.9% | -12.8% | +41% | 3.25 | 27.2% | -17.2% | +233% | 603 | 34% | 1.64 | +1.97% | 0.21 | YES |
| CAT_EARNG_N1_EP | 0.18 | 1.3% | -3.9% | +4% | -0.32 | 0.5% | -5.7% | +1% | -0.09 | 0.9% | -5.7% | +5% | 53 | 32% | 0.80 | -0.66% | 0.00 | no |
| CAT_EARNG_N1_MIX | 2.60 | 18.5% | -17.1% | +66% | 1.08 | 8.3% | -11.6% | +17% | 1.96 | 14.3% | -17.1% | +95% | 379 | 31% | 1.53 | +1.60% | 0.04 | no |
| CAT_EARNG_N0_EP | 2.24 | 4.1% | -3.9% | +13% | 0.80 | 3.7% | -5.5% | +8% | 1.25 | 3.9% | -5.5% | +21% | 97 | 36% | 1.33 | +1.03% | 0.02 | no |
| CAT_EARNG_N0_MIX | 3.10 | 21.9% | -12.8% | +81% | 1.41 | 11.1% | -12.9% | +23% | 2.37 | 17.4% | -15.1% | +123% | 422 | 32% | 1.57 | +1.72% | 0.07 | YES |
| CAT_NOEARN_N1_EP | -1.15 | -3.7% | -14.9% | -11% | 7.92 | 56.0% | -15.1% | +144% | 3.35 | 16.9% | -15.1% | +118% | 446 | 30% | 1.33 | +1.87% | 0.05 | YES |
| CAT_NOEARN_N1_MIX | 1.58 | 13.4% | -19.4% | +46% | 7.06 | 65.7% | -17.2% | +175% | 3.75 | 32.1% | -19.4% | +301% | 759 | 31% | 1.44 | +1.97% | 0.18 | YES |
| CAT_NOEARN_N0_EP | -1.09 | -5.1% | -17.5% | -15% | 4.83 | 53.8% | -21.4% | +137% | 2.03 | 15.1% | -21.4% | +102% | 673 | 27% | 1.14 | +0.83% | 0.03 | YES |
| CAT_NOEARN_N0_MIX | 1.29 | 12.0% | -22.5% | +40% | 5.78 | 63.7% | -20.5% | +168% | 3.13 | 30.4% | -24.2% | +277% | 971 | 28% | 1.24 | +1.21% | 0.13 | YES |

## 2. Pre-registered criteria on 2016-2020

Passed: CAT_ANY_N1_EP, CAT_ANY_N1_MIX, CAT_ANY_N0_EP, CAT_EARN_N1_MIX, CAT_EARN_N0_EP, CAT_EARN_N0_MIX, CAT_EARNG_N0_MIX, CAT_NOEARN_N1_EP, CAT_NOEARN_N1_MIX, CAT_NOEARN_N0_EP, CAT_NOEARN_N0_MIX.
