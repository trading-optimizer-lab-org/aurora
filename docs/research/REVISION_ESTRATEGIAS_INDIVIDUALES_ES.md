# Revisión de las estrategias por separado

Revisión del 2026-10-31. Se leyeron los 74 informes de resultados de `docs/research` buscando cada estrategia
medida sola: factor de beneficio (PF, lo ganado dividido entre lo perdido) y retorno anual. Las cifras de la tabla
final las he comprobado en el informe original; la línea va al lado.

## Lo que hay que saber antes de leer

- Solo v45 midió las estrategias solas en la cuenta real de $5.000 y con el mismo motor que el libro. Es la única
  comparación limpia. Usa costes base, no los de TradeZero de v49; con los de v49 el libro bajó un 37%.
- El PF solo se midió en v35, por estrategia dentro de la cuenta, con entradas limitadas al 30%. Los demás informes
  no lo dan.
- Los CAGR de v18 a v28 son de una cartera con peso fijo sobre $100.000 o más. No se pueden comparar con la cuenta de
  $5.000: v45 dice que no son alcanzables a escala (`V45_RESULTS.md:42`).
- Todo se eligió mirando 2018-2026. Lo que sale bien aquí está inflado.

## Las mejores (cortos en acciones pequeñas, sin datos de pago)

| Estrategia | Qué hace | Sola desde $5.000, 1 año | Ruina | 2023+ | PF (v35) | Fuente |
|---|---|---|---|---|---|---|
| **Subidón A (DS1) al 20%** | Corto a la apertura cuando la acción vale 4 veces o más su mínimo de 5 días | **$7.951** | 0,0% | $8.681 | 2,89 (319 trades) | `V45_RESULTS.md:13`, `V35_RESULTS.md:14` |
| **Subidón B (RU) al 20%** | La misma señal; sale al -50% o a los 5 días | **$7.693** | 0,0% | $8.326 | 8,25 (71 trades) | `V45_RESULTS.md:17`, `V35_RESULTS.md:14` |
| **Fallo nocturno (NS) al 40%** | Corto al cierre de una acción de $2-5 que abrió +30% y se hundió | **$7.373** | 0,3% | $7.168 | 1,71 (399 trades) | `V45_RESULTS.md:15`, `V35_RESULTS.md:14` |

Las tres juntas dieron $23.143 con costes base (`V45_RESULTS.md:12`) y $8.498 con los de TradeZero (v49). Ninguna
sola llega al 100% ni con costes base: la mejor da +59%.

## Descartadas, con el motivo

- **RU al 70%**: sola arruina la cuenta (ruina 37,8%, peor día -82%; `V45_RESULTS.md:14`).
- **ON1** (otra de cierre nocturno): PF 1,13 y trades de -154% (`V35_RESULTS.md:14`). Fuera del libro desde v36.
- **SYMPATHY**: PF 0,53, pierde (`V35_RESULTS.md:14`).
- **XS1 y las demás de dentro del día** (IV, AS, PS, OR, SR, EM...): con buenos números en v26-v28 sobre cartera
  grande, pero piden precio en tiempo real de pago. En la cuenta de $5.000, XS1 pierde dinero porque los datos
  cuestan unos $105 al mes (`V45_RESULTS.md:16`, `:38-40`).
- **W2 de v18 (99% anual)**: es la abuela de DS1, la misma idea de corto tras una subida enorme. El 99% era con costes
  antiguos, una caída del 59,5% y una elección inestable (PBO 81%; `V18_RESULTS.md:22`, `:31`). Con costes
  revisados, su sucesora DS1 bajó de 82% a 38% (`V19_RESULTS.md:61`, `V19R_RESULTS.md:51`).
- **Gap fade S1 y B8R1**: fallaron la prueba sellada de 2023-07 a 2026-10 (`SEALED_TEST_RESULTS.md:33-38`).
- **Compras** (Qullamaggie, Minervini, CANSLIM, rupturas, momentum, cripto, multiactivo): o pierden, o no pasan, o
  están infladas por usar solo empresas que siguen cotizando. La mejor, EP de Qullamaggie dentro del día (PF 1,40,
  26% en 2016-20), baja al 13% en 2021-26 y necesita datos de pago (`QULLAMAGGIE_CATALYST_RESULTS.md:44`,
  `INTRADAY_LOCKED_RESULTS.md:28-29`).
- **Familias de 1 minuto de v44**: solo RO pasó, con un 9,3% anual (`V44_RESULTS.md:51-53`).

## Conclusión

Las tres mejores son las tres que ya forman el libro. No hay ninguna estrategia olvidada que sola dé más. Para
acercarse al 100% con costes reales no basta con quedarse con la mejor; hace falta repartir mejor entre las tres
(v50 lo mide) o una idea nueva.
