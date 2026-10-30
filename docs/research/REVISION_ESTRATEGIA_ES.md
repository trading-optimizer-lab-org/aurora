# Revisión de la estrategia definitiva (v48b)

Revisión del 2026-10-30. Hecha por 6 revisores independientes (código, estadística, ejecución en TradeZero, riesgo,
costes y datos, viabilidad del bot). Los puntos marcados "verificado" los he comprobado en el código o en la web
de TradeZero.

Estrategia revisada: DS1 0,20 / NS 0,40 / RU 0,30, hasta 5 entradas nuevas al día, reglas de la API (TZA), $5.000
en una cuenta. Cifras de v48b: mediana a 1 año $14.411, ruina 1,0%.

## Veredicto

No está lista para operar. El código es correcto y las cifras se reproducen, pero el modelo deja fuera costes y
reglas reales que van en contra, y la ruina del 1% está en el borde de un escalón.

## Lo que está bien

- Sin bugs que cambien los números. 8 tests pasan. Las comprobaciones contra v47 y v48 se reproducen.
- El dropout no mira el resultado. El tope del 1% del volumen usa el día anterior.

## Bloqueantes

1. **Contrato.** Un bot desatendido con el PC apagado necesita autorización escrita de TradeZero.
2. **Préstamo overnight (verificado).** La simulación cobra el préstamo una sola vez por trade: 1% en HTB y 3% en
   HOT, sin importar cuántas noches dura (`scripts/run_v29.py:165-170`, `scripts/run_v28_after.py:342-344`; el
   préstamo por noche existe pero se pasa a 0). TradeZero cobra una comisión variable cada noche, en lotes de 100
   acciones, tres noches los jueves, más un interés de margen de alrededor del 9%. Su página de locates dice que el
   locate normal es solo intradía; su blog dice que pasada la noche se convierte en préstamo overnight con cuota
   diaria. Hay que confirmarlo por escrito. DS1 y RU mantienen hasta 20 sesiones nombres que suelen ser caros de
   prestar: a 300% anual, 10 sesiones cuestan un 8% del trade frente al 3% fijo.
3. **Datos.** Los datos del backtest son Alpaca SIP, de pago. La API de TradeZero no da precios. IEX gratis cubrió
   solo el 62% de los trades en v29. La decisión de las 15:50 necesita precio en tiempo real.

## Riesgos altos

4. **Ruina en el borde.** RU 0,40 da 7,1% y RU 0,30 da 1,0%. El peor candidato RU pierde 187%: a 0,30 es un 56% de la
   cuenta, a 0,40 un 75%. Pocos trades deciden el resultado.
5. **Locates rechazados en los squeezes.** El ensemble quita trades al azar. En la realidad los locates fallan
   justo en los nombres calientes. v47 con 10% sin locate dio 10,3% de ruina en el base.
6. **Selección sobre los mismos datos.** v20-v48b eligieron sobre 2018-2026. En v48b, 2023+ entró en la elección.
7. **Sin simular:** venta forzada por la regla 2:1 a las 15:45, halts, recalls y buy-ins, entradas a mercado a las
   15:55 sin tope de volumen.

## Riesgos medios

- Sesgo de supervivencia: el universo solo tiene valores con barras en Alpaca, sin deslistados.
- La lista Reg SHO del día T se usa en la sesión T (`scripts/run_v28_data.py:465-467`); puede ser un día de
  ventaja si se publica después.
- Las acciones en circulación se usan 45 días después del periodo; los informes de small caps a veces llegan más
  tarde.
- Un solo sorteo de bootstrap para todos los books y semillas: la ruina tiene un error de al menos 0,5 puntos.
- La cifra a 3 años usa los rendimientos de $60.000 por encima de ese nivel y la exagera.

## Rango realista (estimación de un revisor, no medida)

Mediana a 1 año desde $5.000 entre $9.000 y $12.000; ruina entre 2% y 6%; a 3 años entre $35.000 y $65.000. Antes
de contar con los costes overnight reales.

## Lo que falta probar (v49)

Con RU 0,30, 0,25 y 0,20: préstamo por noche a tasas realistas (lotes de 100, jueves triple, margen 9%); locates
rechazados en los nombres HOT; quitar los peores trades RU; aplicar la regla 2:1 a las 15:45; lista Reg SHO con un
día de retraso.
