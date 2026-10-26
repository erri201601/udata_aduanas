# ADR 0027 — Las cuotas compensatorias del corpus, verificadas una por una

- **Fecha:** 2026-10-26
- **Estado:** aceptado (2026-10-26, por delegación de Persona 1)
- **Decide:** Persona 1, que delega lo técnico; queda escrito aquí.
- **Sigue a:** ADR 0009 (cable de acero de China) y ADR 0017 (Anexo 2.5.1
  como índice).

## Contexto

El corpus tiene 25 combinaciones distintas de origen y fracción. Desde el
6-oct sólo una tenía resolución primaria verificada, el cable de China
(ADR 0009). Las demás estaban en `NEEDS_VALIDATION`.

El Anexo 2.5.1 (ADR 0017) dice dónde había cuota en noviembre de 2022. Las
cuotas antidumping duran cinco años salvo que un examen de vigencia las
prorrogue, y las operaciones del corpus son de agosto de 2026. Así que figurar
en el índice no basta: hay que leer lo publicado después.

## Método

1. Cruzar las 25 combinaciones con el índice: 19 no aparecen para ese origen.
2. Para las 6 que aparecen, buscar en el índice de SNICE «Históricos: DOF»
   todo lo publicado después de 2022 sobre esa mercancía y ese origen.
3. Leer los **puntos resolutivos** de cada resolución en el HTML del DOF
   (`curl`, sin resúmenes de prensa ni de buscadores, ADR 0009).

## Resultado, para operaciones de agosto de 2026

| Origen | Fracción | Mercancía | Veredicto | Fuente |
|---|---|---|---|---|
| CN | 7312.10.xx | cable de acero | **cuota 2.58 USD/kg** (ya cargada) | ADR 0009 |
| CN | 7615.10.02 | **ollas de presión** de aluminio | **cuota 92.64 %**, prorrogada 5 años desde el 27-dic-2024 | DOF 2026-03-06, codigo=5781643, puntos 194-195 |
| CN | 7615.10.02 | otros artículos para cocinar de aluminio | cuota con precio de referencia de 10.6 USD/kg, tope de 7.73 USD/kg; vigente hasta el 13-oct-2026 | DOF 2023-03-31 (codigo=5684462, punto 269) y 2023-07-25 (codigo=5696538, punto 77). **No se carga**, ver abajo |
| IN | 7305.11.02, 7305.12.91, 7305.19.99 | tubería de acero al carbono con costura | **cuota 128.24 USD/t**, vigente mientras se tramita el examen iniciado el 6-abr-2026 | DOF 2022-10-03 (codigo=5666803, punto 335 y antecedente 2) y 2026-04-06 (codigo=5784087, punto 29) |
| CN | 6911.10.01, 6912.00.99 | vajilla de cerámica | **sin cuota**. La definitiva se eliminó desde el 26-feb-2026; la provisional del 27-feb duró 4 meses y no hay resolución final posterior en el índice al 26-oct | DOF 2026-02-25 (codigo=5780901, punto 121) y 2026-02-26 (codigo=5780986, puntos 451 y 453) |
| las otras 19 | | | **sin cuota**: no figuran en el Anexo 2.5.1 para ese origen ni hay resolución posterior en el índice de SNICE | ADR 0017 e índice de SNICE |

## Decisión

1. **Cargar las dos cuotas nuevas verificadas**
   (`ingestion.se.cli --cuotas-26-oct`), cada una con su resolución en RAW.
2. **`compensatory_duties.product_terms`** (migración `a2d3970d32ef`): las
   palabras que la partida tiene que decir para que la cuota aplique.
   - La 7615.10.02 abarca todos los artículos de cocina de aluminio, y la cuota
     del 92.64 % es sólo de ollas de presión.
   - La única partida china 7615.10.02 del corpus es un estropajo de acero
     inoxidable, declarado ahí a propósito como anomalía sembrada. Sin este
     filtro, el Espejo le habría exigido la cuota de las ollas.
   - Sin términos, la cuota no se acota por mercancía. Así sigue el cable.
3. **Cuotas ad valorem** (`rate_unit = "PCT"`, moneda `XXX`): el importe es
   tasa × valor en aduana, en la moneda del valor.
4. **La de artículos para cocinar no se carga.** Su importe depende del precio
   unitario por kilo frente a un precio de referencia, y el modelo de la tabla
   no lo sabe calcular. Cargarla como tasa fija afirmaría una cifra que la
   resolución no da. Además vence el 13-oct-2026, con un examen iniciado el
   28-sep-2026.

## Lo que el Espejo dice ahora

- **Tubería de la India:** 15 partidas con cuota. Se declaran en una unidad que
  no es la tonelada y no traen peso neto, así que el hallazgo sale **sin
  importe**. Es lo correcto: no se inventa un factor de conversión.
- **Ollas de presión de China:** el corpus no tiene ninguna. La cuota está
  cargada y probada, y no cae sobre el estropajo.
- **Vajilla de China y las otras 19 combinaciones:** sin cuota, con fuente.
  El Espejo sigue diciendo «no se sabe» cuando no hay fila
  (`compensatory_duty_applies` nunca es `False`). Afirmar «no aplica» exigiría
  conocer todas las resoluciones, y lo de aquí está verificado sólo para el
  corpus.
