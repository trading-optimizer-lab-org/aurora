# Catálogo v2 de estrategias de acciones: resultados (ejecución local, 2026-10-17)

Reglas: [STOCK_CATALOG_V2_PREREGISTRATION.md](STOCK_CATALOG_V2_PREREGISTRATION.md). **Aviso:** el v2 se diseñó después de
ver los resultados del v1, así que 2011-2020 ya no es una prueba limpia. Una buena cifra aquí solo justifica probar
en 2021+ (sin tocar). Sesgo de supervivencia sin corregir.

## 1. Cada señal por separado — validación 2011-2020

| Estrategia | Operaciones | Acierto | Media | Mediana | Profit factor | Rentabilidad total | Días |
|---|---|---|---|---|---|---|---|
| parabolic_short | 483 | 65% | +5.70% | +7.81% | 2.35 | +2,753% | 3.9 |
| weinstein_s50 | 1,656 | 40% | +4.23% | -4.28% | 1.58 | +7,013% | 36.5 |
| darvas_s50 | 1,308 | 41% | +4.12% | -4.09% | 1.56 | +5,387% | 37.7 |
| felipe_s50 | 1,681 | 23% | +2.42% | -4.21% | 1.54 | +4,064% | 18.9 |
| pullback_stage2 | 4,635 | 32% | +1.39% | -3.55% | 1.34 | +6,446% | 12.4 |
| pullback_ind85 | 3,182 | 34% | +1.33% | -3.51% | 1.33 | +4,225% | 12.8 |
| qulla_traits_s20 | 308 | 21% | +1.13% | -3.40% | 1.31 | +348% | 8.2 |
| pullback_breadth | 8,275 | 32% | +1.11% | -3.55% | 1.27 | +9,177% | 12.7 |
| bnf_large | 10,842 | 46% | +0.30% | -0.37% | 1.17 | +3,270% | 3.6 |
| felipe_s20_breadth | 1,748 | 27% | +0.25% | -3.71% | 1.06 | +435% | 10.5 |

## 2. Cada señal por separado — entrenamiento 1995-2010

| Estrategia | Operaciones | Acierto | Media | Mediana | Profit factor | Rentabilidad total | Días |
|---|---|---|---|---|---|---|---|
| weinstein_s50 | 3,754 | 40% | +6.80% | -4.41% | 1.96 | +25,531% | 40.2 |
| darvas_s50 | 2,751 | 40% | +6.52% | -4.32% | 1.90 | +17,939% | 40.7 |
| bnf_large | 14,644 | 48% | +1.00% | -0.30% | 1.51 | +14,576% | 3.6 |
| pullback_ind85 | 6,460 | 30% | +1.23% | -3.92% | 1.27 | +7,940% | 12.1 |
| felipe_s50 | 3,629 | 20% | +1.28% | -4.91% | 1.25 | +4,660% | 18.6 |
| pullback_stage2 | 10,580 | 29% | +0.70% | -3.84% | 1.16 | +7,443% | 11.9 |
| pullback_breadth | 18,801 | 29% | +0.45% | -3.95% | 1.10 | +8,403% | 11.9 |
| parabolic_short | 1,251 | 52% | +0.54% | +1.40% | 1.08 | +681% | 4.0 |
| qulla_traits_s20 | 660 | 21% | -0.06% | -4.37% | 0.99 | -42% | 8.3 |
| felipe_s20_breadth | 4,099 | 24% | -0.30% | -4.29% | 0.93 | -1,239% | 10.3 |

## 3. Cartera con una sola cuenta — validación 2011-2020

Ninguna pasa los tres criterios.

| Estrategia | Sortino mensual | Rentabilidad/año | Caída máx. | Invertido |
|---|---|---|---|---|
| spy | 1.59 | 13.8% | -33.7% | - |
| pullback_stage2 | 0.67 | 6.4% | -53.9% | 67% |
| pullback_ind85 | 0.62 | 5.6% | -33.6% | 58% |
| pullback_rank_ind | 0.25 | 1.9% | -50.5% | 71% |
| pullback_rank_close | -0.00 | -1.1% | -63.0% | 71% |
| pullback_rank_random | 0.03 | -1.1% | -56.9% | 71% |
| pullback_risk025 | 0.67 | 5.7% | -41.7% | 65% |
| weinstein_s50 | 1.28 | 11.0% | -31.1% | 63% |
| darvas_s50 | 1.26 | 9.2% | -24.8% | 55% |
| felipe_s50 | 1.39 | 15.1% | -30.5% | 62% |
| qulla_traits_s20 | 0.80 | 3.3% | -16.8% | 12% |
| bnf_large | 2.24 | 17.6% | -45.7% | 49% |
| parabolic_short | 3.26 | 5.9% | -6.7% | 4% |
| pullback_breadth | 0.85 | 8.8% | -41.4% | 75% |
| felipe_s20_breadth | 0.73 | 5.5% | -30.7% | 49% |

## Lectura

- **Aguantar más gana**: salir al perder la media de 50 días sube el PF de Weinstein, Darvas y Felipe a 1,54-1,58
  (validación) y 1,25-1,96 (entrenamiento). En cartera, Felipe con SMA50 hace 15,1%/año (SPY 13,8%) con -30,5% de caída.
- **Retroceso 9/21**: Etapa 2 o industria top 15% suben el PF a 1,33-1,34. Elegir entre señales por industria, por
  cercanía a la media o al azar empeora la cartera frente al orden por fuerza relativa.
- **BNF en las 500 más grandes con stop**: PF 1,51 (entrenamiento) y 1,17 (validación); cartera Sortino 2,24 y 17,6%/año,
  pero -45,7% de caída.
- **Corto en subidas parabólicas**: PF 2,35 en validación, pero 294 de sus 483 operaciones son de 2020 (meme/COVID);
  sin 2020, +2,3% por operación. En entrenamiento PF 1,08. No incluye coste de préstamo de acciones ni la posibilidad
  de que no haya acciones para prestar, que en estos valores suelen ser grandes.
- **Rasgos de Qullamaggie** y **filtro de amplitud**: mejoras pequeñas o nulas.
