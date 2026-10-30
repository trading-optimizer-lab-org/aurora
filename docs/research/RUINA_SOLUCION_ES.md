# La ruina frágil del book: causa y plan para arreglarla

Revisión del 2026-10-30. Datos de v47d (run 40933324435) y v48d (run 41051524146), a $10.000 con costes base.
Todo dentro de muestra.

## 1. La causa

**El tamaño de cada trade no depende del riesgo.** Cada trade entra con
`w = min(tamaño del miembro, 1% del volumen en dólares del día anterior / cuenta)`:
- DS1 0,20, RU 0,70 y NS 0,40 de la cuenta en un solo nombre;
- el 37-54% de HOLO, TROO y RVSN era solo el tope de liquidez.

**Con RU al 70% la capacidad se llena enseguida.** El límite de exposición bruta es 2,0, así que caben unas dos
posiciones RU a la vez. Por eso la cuenta solo toma **72 de 230** candidatos RU (31%), y cuáles entran depende del
calendario, no de la calidad del trade.

**Esos 72 salieron con suerte:**

| RU | media | p1 | peor | trades < -50% | trades < -100% | peor movimiento en contra |
|---|---|---|---|---|---|---|
| los 230 candidatos | +16,1% | -105,8% | -187% | 5,2% | 1,3% | +847% |
| los 72 tomados | +23,4% | -29,8% | -30% | **0,0%** | **0,0%** | +127% |

Los desastres se quedaron todos fuera por falta de hueco:

| candidato fuera | resultado | peso que habría tenido |
|---|---|---|
| UONE | -187% | 0,39 |
| DFNS | -148% | 0,10 |
| XHLD | -108% | 0,49 |
| MRIN | -99% | 0,47 |
| RVSN | -88% | 0,47 |

Basta cambiar un poco qué trades se hacen, por un día perdido, un locate rechazado o decidir a las 15:50, para que
entre uno de ellos.

**Los tamaños de v32-v39 se eligieron midiendo la ruina sobre ese único conjunto con suerte.** Por eso el 70% de RU
parece seguro y no lo es.

## 2. Crecimiento de un trade según el tamaño, con todos los candidatos

Media de log(1 + f x resultado del trade). Una pérdida mayor que la cuenta cuenta como -100%.

| f | 0,15 | 0,20 | 0,25 | 0,30 | 0,40 | 0,50 | 0,70 |
|---|---|---|---|---|---|---|---|
| DS1 | 0,0183 | 0,0237 | 0,0287 | 0,0333 | 0,0409 | 0,0439 | 0,0354 |
| NS | 0,0058 | 0,0075 | 0,0090 | 0,0104 | 0,0126 | 0,0137 | -0,0003 |
| RU | 0,0222 | 0,0287 | 0,0347 | 0,0401 | 0,0491 | 0,0524 | **0,0071** |

- RU al 70% está pasado del precipicio. Con el 50% tendría 7 veces más crecimiento por trade, porque un -150% al
  70% se lleva la cuenta entera.
- La tabla trata cada trade solo. En la cuenta hay varias posiciones a la vez y las squeezes llegan juntas, como en
  junio de 2020 o febrero de 2024. El óptimo real es más bajo que el 0,50 de un trade aislado; la regla clásica de
  medio Kelly lo pone hacia 0,25.
- DS1 está por debajo de su óptimo aislado: a 0,20 da 0,0237 y a 0,30 daría 0,0333.

## 3. La idea para no perder rendimiento: más nombres, cada uno más pequeño

- Con RU al 0,25 caben unas 8 posiciones en vez de 2. La cuenta tomaría muchos más de los 230 candidatos, y el
  resultado se parecería a la distribución completa y no a 72 trades con suerte.
- Crecimiento total RU, cuenta a mano (supuesto, no medido):
  - ahora: 72 trades a ~0,45 sobre un conjunto que no tiene desastres;
  - propuesta: unos 150-200 trades a 0,25 con 0,0347 cada uno, desastres incluidos.
  - Son del mismo orden. La diferencia es que la segunda cifra no depende de la suerte.
- El peor trade al 0,25 cuesta un 47% de la cuenta (UONE -187% x 0,25). Hace daño pero no arruina, y un 0,20 lo deja
  en 37%.

**Comparar con el base de $22.006 es injusto.** Esa cifra es la del conjunto con suerte. El base honesto, con
pequeñas perturbaciones, se mueve entre $16k y $19k con un 7-10% de ruina (v47: O1, M05, M10, U10). "Sin perder
rendimiento" tiene que medirse contra eso.

## 4. Otras vías y por qué no van primero

| vía | por qué no |
|---|---|
| stops | v46: todos los stops del 10% al 50% destruyen la ventaja. El book gana con nombres que siguen subiendo un rato antes de caer. Un stop muy ancho (+150%) apenas ayuda y los gaps lo saltan |
| cubrirse con opciones | casi ninguna de estas small caps tiene opciones líquidas; v42 mostró que las coberturas largas pierden |
| bajar la exposición bruta total | reduce el rendimiento sin atacar la concentración en un nombre |
| filtro de squeeze (HOT, float pequeño) | candidato para una segunda prueba; v36 lo descartó, pero midiendo sobre el conjunto con suerte |

## 5. Prueba propuesta (v48), para pre-registrar

1. **Medida honesta: un conjunto de 30 perturbaciones.**
   - Cada semilla quita al azar el 10% de los candidatos, con semilla por símbolo y día, y recalcula la cuenta.
   - Esto cambia qué trades entran, igual que los días perdidos o los locates rechazados de la vida real.
   - Se publica la mediana y la ruina medias del conjunto, y la ruina de la peor décima parte de semillas.
   - El base pasa por lo mismo; su resultado es la referencia honesta.
2. **Rejilla de tamaño por nombre:**
   - RU 0,70 / 0,50 / 0,40 / 0,30 / 0,25 / 0,20 / 0,15;
   - NS 0,40 / 0,30 / 0,25;
   - DS1 0,20 / 0,25 / 0,30;
   - máximo de entradas nuevas por día 3 / 5.
   - El tope del 1% del volumen se mantiene. La exposición bruta se queda en 2,0 por la regla 2:1 de TZ.
3. **Elegir con 2018-2022 y comprobar con 2023+**, como en v39, para no volver a elegir sobre los mismos datos.
4. **Criterios:**
   - ruina del conjunto <= 2,5% con costes base y HOT 5%;
   - mediana del conjunto >= la del base honesto;
   - las dos mitades de símbolos positivas;
   - comprobación final con las reglas reales de la API (TZA).

Coste: la repetición minuto a minuto depende del tamaño, no de la semilla. Son unas 1.500 repeticiones más la cuenta
de cada semilla; cabe en un run de Actions de 50-100 servidores.
