# ADR 0011 — El contrato de PROSEC y Regla 8ª

- **Fecha:** 2026-10-13
- **Estado:** aceptado (2026-10-13)
- **Decide:** Persona 1
- **Carga:** Persona 2 (tarea 3 del encargo del 13-oct)
- **Consume:** Opportunity Finder (`core/opportunity/programs.py`), ya implementado

## Contexto

El §23 pide que el Opportunity Finder busque PROSEC y Regla 8ª, y el §11
nombra sus fuentes (SNICE). Hoy sólo encuentra sobrepagos. El motor ya tenía
los tipos `PROSEC` y `REGLA_8A`, con sus condiciones, pero nada que los
alimentara, y cada informe decía «PROSEC, Regla 8ª y preferencias no se
evaluaron: sus catálogos no están cargados».

Se define el contrato **antes** de la carga, para que Persona 2 cargue
directamente en esta forma y el consumo ya exista cuando lleguen los datos. Es
el orden contrario al de la cuota compensatoria (ADR 0009), donde se cargó
primero y después se buscó lector. Aquí no hay fila sin consumidor.

## Decisión

### 1. `regulatory.prosec_rates`: la tasa de un sector para una fracción

| Columna | Qué es |
|---|---|
| `sector_code` | El inciso del art. 4 del Decreto PROSEC, tal como lo escribe («I», «XIX») |
| `sector_name` | Como lo nombra el decreto |
| `fraction_code` | 8 dígitos sin puntos |
| `igi_rate` | Como fracción (0.05, no 5). «Ex.» (exento) = 0 |
| `is_partial` | La fracción aparece acotada en el decreto |
| `scope_note` | La acotación íntegra; `NULL` = toda la fracción |

Clave natural `(sector_code, fraction_code, valid_from)`: **una fracción puede
estar en varios sectores con tasas distintas.** Con vigencia y procedencia
(`RegulatoryMixin`, `DataOriginMixin`) como cualquier tabla de `regulatory`.

### 2. `regulatory.regla_8a_fractions`: qué 9802 corresponde a cada sector

`sector_code`, `sector_name`, `fraction_code` (la 9802.00.xx) y `scope_note`
(exclusiones del sector, íntegras; `NULL` = no se conocen, no «no hay»).

**La tasa no se guarda aquí.** La LIGIE ya publica la 9802.00.01–.38 con su
arancel, y ya están cargadas en `tariff_fractions` (comprobado el 13-oct: 38
fracciones vigentes). Dos copias de una tasa acaban diciendo cosas distintas.
Una 9802 sin tasa vigente en la LIGIE se omite; no se supone cero.

`sector_code` usa la misma codificación que `prosec_rates`.

### 3. `operational.clients.prosec_sector_codes`

`ARRAY(VARCHAR(8))`, nullable. Los sectores en que **opera** el importador.
`NULL` = no se sabe; `[]` = consta que en ninguno.

No dice que esté **inscrito**: eso sigue siendo una condición que se comprueba
fuera del sistema y viaja en cada oportunidad. Sirve para no ofrecerle a una
mueblera la tasa del sector automotriz.

### 4. Cómo se consume

`database/repositories/programas.py::cargar_programas` lee lo vigente en la
fecha de la operación, una vez por pedimento. `core/opportunity/programs.py::from_programs`
decide, por partida:

- **Sólo cuenta una tasa menor que la aplicada** (la LIGIE de la fracción
  declarada). Sin tasa aplicada conocida no se devuelve nada, y el informe lo
  dice.
- **Sin sector del importador:** PROSEC sale **sin monto**, con la lista de
  sectores y tasas posibles. La Regla 8ª **no se evalúa**: hay una 9802 por
  sector y elegirla sería inventar.
- **Con sector:** se cuantifica con la mejor tasa de **sus** sectores y se
  mencionan las demás. **No se suman alternativas.**
- **Acotaciones y exclusiones** se añaden a las condiciones de la
  oportunidad, con el texto íntegro.
- Una tasa `SYNTHETIC` hace simulada la oportunidad aunque el pedimento sea
  real (§33).
- Todo nace `POTENTIAL` (§23).

`OpportunityReport.total_potential` toma ahora **el mayor por partida**, no la
suma. PROSEC, Regla 8ª y un sobrepago sobre la misma partida son caminos
distintos al mismo dinero; sumarlos prometería cobrar dos veces el mismo IGI.

`catalogo is None` (ninguna fila vigente en las dos tablas) y «se consultó y no
hay» se distinguen: con lo primero el informe sigue diciendo que no se evaluaron.

## Lo que queda `NEEDS_VALIDATION` para el reconocimiento de Persona 2

- **Si el decreto marca acotaciones con «Ex.» antes de la fracción** (como la
  LIGIE) o de otra forma. `is_partial` + `scope_note` cubren cualquiera de las
  dos, pero el parser tiene que distinguir «Ex.» en la **tasa** (exento = 0) de
  «Ex.» en la **fracción** (acotación).
- **Si los incisos de sector de la Regla 8ª coinciden con los del art. 4 del
  Decreto PROSEC.** Las descripciones de la 9802.00.01–.25 nombran los mismos
  programas sectoriales, pero la 9802.00.26–.38 («al amparo de la autorización
  a que se refiere la Regla 8ª») no. Si no coinciden, se dice en el
  reconocimiento y se revisa este contrato **antes** de cargar.
- **Las exclusiones de la Regla 8ª por sector**: de dónde salen y si caben en
  `scope_note` como texto o necesitan estructura.

## Riesgos conocidos

- **La tasa aplicada es la de la LIGIE de la fracción declarada**, no la que el
  pedimento realmente pagó. Si el importador ya usó una preferencia de tratado,
  el sistema puede sugerir PROSEC sobre una tasa que no pagó. Es una
  oportunidad `POTENTIAL` con condiciones y no se presenta como ahorro, pero
  cuando el corpus traiga la tasa efectiva por partida conviene usarla.
- **Ningún cliente del corpus tiene sector hoy** (`industry` también está
  vacío en los 16). Hasta que el generador sintético los asigne, PROSEC saldrá
  sin monto y la Regla 8ª sin evaluar. Es lo correcto con esos datos.

## Para el generador sintético (§24, §25)

El escenario `MISSED_PROSEC` necesita: un cliente con `prosec_sector_codes`, una
fila de `prosec_rates` para la fracción de la partida con tasa menor a la
LIGIE, y un pedimento que declare la tasa general. El ground truth (§26) es
una oportunidad `PROSEC` en esa partida.

## La carga (20-oct)

Persona 2 localizó el documento en su reconocimiento (#247); Persona 1 lo cargó
(`python -m ingestion.se.cli --target local --prosec` y `--regla-8a`).

**PROSEC.** Compilación SNICE del Decreto, con reformas hasta el DOF 26-08-2024.
Del artículo 5 salen **2 649 tasas** en 23 sectores (el XXIV, Fertilizantes, no
tiene filas), **467 con acotación**. Se leen las celdas de las tablas del PDF
(`pdfplumber`), no el texto: el texto repartía la acotación entre filas
vecinas. Comprobado contra el texto del mismo PDF: 0 diferencias de tasa, y las
895 fracciones distintas están vigentes en la LIGIE.

- «Ex.» en el arancel es **exento** (tasa 0); «Únicamente:»/«Excepto:» en la
  acotación es `is_partial`.
- `valid_from` = 2024-08-26, la última reforma que incluye la compilación. Antes
  de esa fecha no se afirma ninguna tasa. Reformas posteriores:
  `NEEDS_VALIDATION`, las vigila el DOF Watcher.

**Cambio de contrato:** la clave única pasa a ser
`(sector_code, fraction_code, scope_note, valid_from)` con `NULLS NOT DISTINCT`
(migración `a7c3e91b2d40`). El decreto lista la misma fracción dos veces en un
sector con acotaciones opuestas y tasas distintas (46 casos: «Únicamente: …» al
5 %, «Excepto: …» al 10 %). El consumo ya lo admitía: elige la menor tasa y lleva
su acotación como condición.

**Regla 8ª.** De la propia LIGIE: **24 fracciones 9802 con sector** (la
Siderúrgica tiene dos: productores directos e indirectos, al 5 %). 14 no nombran
programa sectorial (la .24 y de la .26 a la .38) y no se cargan.
