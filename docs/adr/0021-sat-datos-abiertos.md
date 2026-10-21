# ADR 0021 — SAT Datos Abiertos: cifras de comercio exterior

- **Fecha:** 2026-10-21
- **Estado:** aceptado (2026-10-21, por delegación de Persona 1)
- **Decide:** Persona 1, que delega lo técnico; queda escrito aquí.

## Contexto

El scorecard (§44) tenía «ANAM / SAT / Data México» en cero. El 20-oct se
comprobó cada fuente:

- **ANAM:** `anam.gob.mx/estadisticas-anam/` responde **410 (Gone)**. Queda
  `SOURCE_NOT_AVAILABLE` hasta encontrar dónde publica ahora.
- **Data México:** la página y su API no responden (timeout). También
  `SOURCE_NOT_AVAILABLE`.
- **SAT Datos Abiertos** (`sat.gob.mx/minisitio/DatosAbiertos/dyp.html`)
  responde. Publica tres `.xls` de comercio exterior, mensuales desde enero de
  2010: pedimentos pagados de importación, pedimentos pagados de exportación y
  recaudación de comercio exterior por impuesto (IVA, IGI, DTA, IEPS, ISAN,
  otros, total).

El maestro (§11) las pide para «calibración, benchmarks, estadísticas».

## Decisión

1. **Tabla `regulatory.trade_statistics`:** una cifra por fuente, serie, año y
   mes. La vigencia es el mes al que se refiere la cifra (del día 1 al último
   día). `data_origin = OFFICIAL`. Las notas al pie del SAT se guardan
   verbatim, entre ellas el cambio de la AGA al SAT en 2022 y las «cifras
   preliminares».
2. **Ningún motor calcula dinero con ellas** (regla 6). Son referencia: cuánto
   se importa y se recauda en el país, para calibrar el generador sintético y
   dar contexto en el tablero.
3. **Acumulada o del mes: se comprueba, no se supone.** El archivo no lo dice.
   Los pedimentos crecen mes a mes y vuelven a empezar cada enero (diciembre de
   2010, 5.59 millones; enero de 2011, 0.45), así que son acumulados en el
   año. La recaudación sube y baja, así que es del mes. El cargador lo
   verifica en cada año: si una serie marcada como acumulada baja, la carga se
   detiene (`NEEDS_VALIDATION`).
4. **Una cifra revisada se actualiza.** El SAT corrige las preliminares; si el
   valor cambia, la fila se actualiza y apunta al RAW nuevo.
5. **`xlrd>=2,<3`** como dependencia nueva, porque los `.xls` (BIFF) no los lee
   `openpyxl`. Los floats de xlrd pasan a `Decimal` por `repr`, la
   representación más corta que vuelve al mismo float, para no arrastrar
   ruido binario.
6. **RAW por archivo**, con el hash en la clave
   (`sat/datos_abiertos/{nombre}_{sha16}.xls`).

## Resultado

1 800 cifras: 200 meses de cada serie de pedimentos y 1 400 de recaudación
(7 impuestos), de enero de 2010 a agosto de 2026.

## Lo que no se hace aquí

- Mostrarlas en el tablero.
- Usarlas para calibrar el generador sintético.

Cada una va en su propio PR, cuando haya quien las consuma.

## Corrección 2026-10-21 — ocho decimales

La primera carga dio 1 800 cifras, y la segunda **504 «cambiadas»** cuando
debía dar 0. La recaudación viene en millones de pesos **con centavos**, así
que tiene 8 decimales (30.84343944 = $30 843 439.44), y la columna
`Numeric(20, 6)` redondeaba los centavos: cada recarga veía una cifra distinta.
Ahora la columna es `Numeric(24, 8)` y el parser cuantiza a 8 decimales, el
último dígito con sentido. Lo que viene después es ruido del float.
