# SP500 Search Method Benchmark Expanded

## Objetivo

Comparar de forma reproducible la eficiencia de búsqueda de los métodos
solicitados sobre el mismo espacio causal de estrategias SPY. El resultado no
es una afirmación de que un método sea universalmente mejor.

## Contrato congelado

- 23 métodos, exactamente las mismas siete semillas del benchmark anterior.
- Un snapshot SPY inmutable, cargado solo hasta `2010-12-31`.
- Búsqueda: `1998-01-01..2005-12-31`.
- Auditoría congelada: `2006-01-01..2010-12-31`.
- Validación `2011-01-01..2020-12-31`: no se carga.
- `OOS_LOCKED >= 2021-01-01`: no se carga.
- 32 candidatos Scrambled Sobol comunes, evaluados a fidelidad completa.
- Presupuesto por método/semilla: 256 unidades equivalentes a una evaluación
  completa, y 15 minutos de pared.
- Fidelidades: `0.25`, `0.50` y `1.00`; solo candidatos con `1.00` pueden
  entrar en los cinco candidatos congelados.
- Evaluador, espacio, reglas de fechas, costes, ejecución al siguiente open y
  workers son comunes.

## Métodos

1. Random
2. Scrambled Sobol
3. TPE
4. SMAC/RF-SMBO
5. Differential Evolution
6. Genetic Programming
7. GP + TPE híbrido
8. DEHB real
9. BOHB
10. Hyperband
11. ASHA
12. CMA-ES
13. PSO
14. Bayesian Optimization con Gaussian Processes
15. TuRBO
16. Optuna-style TPE con median pruning
17. Nevergrad OnePlusOne/NGOpt-style
18. NSGA-II
19. Latin Hypercube
20. Halton
21. Successive Halving
22. Population-Based Training
23. Surrogate-assisted avanzado con surrogate RBF y búsqueda local

Las implementaciones son autocontenidas para conservar el lock de GitHub. Por
eso `Optuna` y `Nevergrad` identifican sus algoritmos de búsqueda, no una
dependencia externa que pueda degradarse silenciosamente o cambiar de versión.
La manifestación de cada run registra la implementación exacta usada.

## Interpretación

La métrica principal es la mediana entre semillas de la CAGR de auditoría de
los cinco candidatos congelados a fidelidad completa. La eficiencia de búsqueda
se mide aparte como el área bajo la mejor CAGR de búsqueda a fidelidad completa
frente al coste consumido. Un intervalo bootstrap pareado del 95 % compara el
primero y el segundo; si incluye cero, el estado es `NO_CLEAR_WINNER`.

El pipeline previsto es:

`prepare -> preflight -> smoke -> 161 method/seed units -> freeze_check -> audit -> aggregate -> independent_verify -> conclude`
