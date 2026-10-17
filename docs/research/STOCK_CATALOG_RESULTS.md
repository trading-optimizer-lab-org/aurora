# Catálogo de estrategias de acciones: resultados (ejecución local, 2026-10-17)

Reglas: [STOCK_CATALOG_PREREGISTRATION.md](STOCK_CATALOG_PREREGISTRATION.md), escritas antes de calcular nada.
Datos: catálogo local `free_us_daily` (Yahoo), 2.938 acciones operables, 1993-2020. 2021 en adelante no se ha leído.
**Sesgo de supervivencia sin corregir** (decisión del propietario): solo están las empresas que siguen cotizando, así
que todo sale optimista, sobre todo lo que compra acciones hundidas (BNF).

**Confirmado en GitHub** ([run 39042775310](https://github.com/trading-optimizer-lab-org/aurora/actions/runs/39042775310),
`stock-ideas.yml`, datos descargados de nuevo de Yahoo): 3.205 de las 3.263 acciones (98,2%); 3.203 con rentabilidades
idénticas a las locales (dos con revisiones de datos: GORO y NFE). Los profit factors coinciden con los locales a ±0,04 en
casi todas las reglas (por ejemplo, retroceso 9/21: 1,26 en GitHub frente a 1,27 en local). La excepción es el Episodic Pivot,
con solo 135 operaciones (0,78 frente a 1,00), demasiado pocas para ser estable. Las conclusiones no cambian.

## 1. Cada señal por separado (sin límite de dinero) — validación 2011-2020

Rentabilidad total = suma de todas las operaciones (1 unidad en cada una). Coste 10 pb por lado incluido.

| Estrategia | Operaciones | Acierto | Media | Mediana | Profit factor | Rentabilidad total | Días |
|---|---|---|---|---|---|---|---|
| pullback_s20 | 7,830 | 32% | +1.09% | -3.61% | 1.27 | +8,538% | 12.7 |
| pullback_s20_noind | 14,236 | 33% | +0.92% | -3.52% | 1.22 | +13,041% | 12.7 |
| weinstein_s20 | 1,869 | 39% | +1.00% | -3.42% | 1.18 | +1,862% | 16.5 |
| darvas_s20 | 1,478 | 41% | +0.93% | -3.02% | 1.16 | +1,371% | 16.8 |
| weinstein_s20_noind | 2,530 | 40% | +0.87% | -3.07% | 1.16 | +2,192% | 16.5 |
| felipe_s20 | 1,701 | 28% | +0.55% | -3.66% | 1.14 | +936% | 10.8 |
| darvas_s20_noind | 1,899 | 40% | +0.54% | -3.12% | 1.10 | +1,034% | 16.8 |
| ep_s20_noind | 275 | 35% | +0.52% | -3.95% | 1.10 | +142% | 13.9 |
| qulla_s20 | 3,405 | 21% | +0.20% | -3.33% | 1.06 | +684% | 8.3 |
| bnf_reversion | 29,419 | 45% | +0.11% | -0.44% | 1.05 | +3,224% | 3.7 |
| burst_fast | 8,254 | 26% | +0.16% | -2.76% | 1.05 | +1,334% | 5.6 |
| burst_5d | 8,829 | 39% | +0.11% | -2.56% | 1.03 | +940% | 3.8 |
| ep_s20 | 133 | 35% | +0.01% | -4.00% | 1.00 | +2% | 13.6 |
| felipe_s20_noind | 2,855 | 26% | -0.03% | -3.78% | 0.99 | -72% | 10.5 |
| felipe_5d | 1,841 | 40% | -0.09% | -2.42% | 0.97 | -161% | 3.9 |
| burst_fast_noind | 16,737 | 25% | -0.13% | -2.85% | 0.96 | -2,098% | 5.4 |
| burst_5d_noind | 17,971 | 38% | -0.15% | -2.76% | 0.95 | -2,634% | 3.7 |
| qulla_s20_noind | 6,021 | 19% | -0.17% | -3.58% | 0.95 | -1,053% | 8.0 |
| qulla_s10 | 3,590 | 24% | -0.22% | -2.97% | 0.93 | -806% | 5.6 |
| qulla_half3 | 3,709 | 35% | -0.20% | -1.90% | 0.92 | -726% | 4.5 |
| felipe_5d_noind | 3,094 | 39% | -0.41% | -2.59% | 0.86 | -1,279% | 3.9 |
| qulla_half3_noind | 6,569 | 35% | -0.37% | -2.08% | 0.85 | -2,417% | 4.3 |
| qulla_s10_noind | 6,363 | 23% | -0.72% | -3.19% | 0.79 | -4,552% | 5.3 |

## 2. Cada señal por separado — entrenamiento 1995-2010

| Estrategia | Operaciones | Acierto | Media | Mediana | Profit factor | Rentabilidad total | Días |
|---|---|---|---|---|---|---|---|
| bnf_reversion | 33,776 | 48% | +1.22% | -0.26% | 1.68 | +41,051% | 3.7 |
| weinstein_s20 | 4,381 | 39% | +2.40% | -3.28% | 1.45 | +10,532% | 17.1 |
| weinstein_s20_noind | 6,321 | 39% | +2.05% | -3.42% | 1.38 | +12,926% | 17.0 |
| darvas_s20 | 3,217 | 39% | +2.09% | -3.40% | 1.38 | +6,739% | 17.3 |
| darvas_s20_noind | 4,414 | 39% | +1.84% | -3.37% | 1.33 | +8,102% | 17.3 |
| pullback_s20 | 17,720 | 29% | +0.31% | -4.02% | 1.07 | +5,424% | 11.9 |
| pullback_s20_noind | 32,907 | 29% | +0.16% | -3.97% | 1.03 | +5,129% | 12.0 |
| ep_s20 | 118 | 29% | +0.06% | -4.09% | 1.01 | +8% | 12.9 |
| qulla_s20 | 6,692 | 20% | +0.00% | -4.09% | 1.00 | +13% | 8.3 |
| ep_s20_noind | 279 | 30% | +0.00% | -4.06% | 1.00 | +0% | 12.3 |
| felipe_s20 | 3,696 | 24% | -0.20% | -4.23% | 0.95 | -737% | 10.3 |
| burst_5d_noind | 39,810 | 38% | -0.26% | -2.93% | 0.93 | -10,399% | 3.8 |
| burst_5d | 19,672 | 38% | -0.29% | -2.99% | 0.92 | -5,689% | 3.8 |
| qulla_s20_noind | 12,266 | 19% | -0.45% | -4.22% | 0.90 | -5,520% | 8.1 |
| burst_fast | 18,776 | 24% | -0.37% | -3.07% | 0.90 | -7,015% | 5.2 |
| felipe_5d | 4,041 | 38% | -0.36% | -2.73% | 0.89 | -1,445% | 3.8 |
| felipe_s20_noind | 6,401 | 23% | -0.54% | -4.32% | 0.88 | -3,486% | 10.2 |
| qulla_s10 | 7,042 | 24% | -0.47% | -3.56% | 0.87 | -3,309% | 5.5 |
| felipe_5d_noind | 7,067 | 38% | -0.45% | -2.80% | 0.86 | -3,160% | 3.8 |
| burst_fast_noind | 37,986 | 24% | -0.51% | -3.06% | 0.86 | -19,262% | 5.2 |
| qulla_half3 | 7,278 | 34% | -0.48% | -2.34% | 0.84 | -3,480% | 4.4 |
| qulla_s10_noind | 12,989 | 23% | -0.79% | -3.68% | 0.79 | -10,301% | 5.4 |
| qulla_half3_noind | 13,491 | 33% | -0.69% | -2.49% | 0.78 | -9,252% | 4.3 |

## 3. Cartera con una sola cuenta (0,5% de riesgo por operación, máx. 20% por posición) — validación 2011-2020

Ninguna pasa los tres criterios (Sortino >= 2, más que el SPY, caída no peor que -25%).

| Estrategia | Sortino mensual | Sharpe mensual | Rentabilidad/año | Caída máx. |
|---|---|---|---|---|
| spy | 1.59 | 0.98 | 13.8% | -33.7% |
| equal_weight_universe | 1.25 | 0.79 | 14.2% | -42.3% |
| felipe_5d | -0.36 | -0.23 | -2.0% | -43.7% |
| felipe_s20 | 0.84 | 0.44 | 6.2% | -29.3% |
| felipe_5d_noind | -0.65 | -0.44 | -5.7% | -61.7% |
| felipe_s20_noind | -0.41 | -0.28 | -4.7% | -64.9% |
| qulla_s10 | -0.40 | -0.25 | -4.8% | -69.1% |
| qulla_s20 | 0.09 | 0.05 | -0.2% | -58.5% |
| qulla_half3 | -0.45 | -0.28 | -3.8% | -58.6% |
| qulla_s10_noind | -1.00 | -0.78 | -14.2% | -85.5% |
| qulla_s20_noind | -0.50 | -0.35 | -8.6% | -75.3% |
| qulla_half3_noind | -0.75 | -0.53 | -9.0% | -79.8% |
| pullback_s20 | 0.68 | 0.36 | 6.7% | -50.6% |
| pullback_s20_noind | 0.54 | 0.30 | 5.3% | -52.5% |
| burst_fast | 0.47 | 0.25 | 4.0% | -62.3% |
| burst_5d | 0.38 | 0.20 | 2.7% | -59.2% |
| burst_fast_noind | 0.15 | 0.09 | -0.5% | -71.2% |
| burst_5d_noind | 0.40 | 0.21 | 2.7% | -69.5% |
| ep_s20 | 0.22 | 0.11 | 1.0% | -10.4% |
| ep_s20_noind | 0.98 | 0.48 | 3.2% | -13.0% |
| darvas_s20 | 0.29 | 0.15 | 1.6% | -24.5% |
| darvas_s20_noind | 0.09 | 0.05 | 0.6% | -31.6% |
| weinstein_s20 | 0.37 | 0.18 | 2.1% | -30.6% |
| weinstein_s20_noind | 0.37 | 0.20 | 2.4% | -35.8% |
| bnf_reversion | 3.26 | 1.65 | 34.1% | -57.4% |
| blend_t | 1.88 | 0.92 | 12.8% | -27.8% |

## Lectura rápida

- Mejor regla por operación: **retroceso a EMAs 9/21 que suben** (PF 1,27 en validación, 1,07 en entrenamiento).
- **Weinstein Etapa 2 y Darvas**: positivas en los dos periodos (PF 1,38-1,45 antes, 1,16-1,18 después).
- **Filtro de industria (Jacobs)**: mejora las rupturas (Felipe 0,99 → 1,14; Qullamaggie 0,95 → 1,06).
- **Salir pronto** (5 días o la mitad a los 3 días) pierde en casi todas.
- **BNF**: PF 1,68 antes y 1,05 después; la cartera gana porque elige las caídas más profundas, y el sesgo de
  supervivencia lo infla.

El informe completo en inglés generado por el código está en
[STOCK_CATALOG_REPORT_LOCAL.md](STOCK_CATALOG_REPORT_LOCAL.md).
