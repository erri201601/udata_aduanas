# ADR 0009 — Cuota compensatoria: cable de acero de China, de punta a punta

- **Fecha:** 2026-10-06
- **Estado:** aceptado e implementado (2026-10-06/07, Persona 2)
- **Decide:** Persona 1
- **Contexto de:** `docs/RECONOCIMIENTO_CUOTAS_COMPENSATORIAS.md` (reconocimiento
  previo, 3 combinaciones candidatas) + corrección de Persona 1 sobre ese
  reconocimiento (6-oct)

## Contexto

El reconocimiento de cuotas compensatorias propuso 3 combinaciones
candidatas (origen, fracción) del corpus con posible cuota real. Persona 1
corrigió dos de las tres y acotó el alcance a **una sola**, con una
corrección de método que vale la pena dejar escrita porque va a volver a
pasar:

**La fuente citada en el reconocimiento no decía lo que el reconocimiento
afirmaba.** El enlace puesto para "la prórroga de 2026" del cable de acero
(`codigo=5619643`) es la resolución del **examen de vigencia de 2021**
(periodo examinado 1-jul-2018 a 30-jun-2019, opinión de la Comisión
4-may-2021): confirma los 2.58 USD/kg de 2014, pero no menciona ninguna
prórroga de 2026. Las tres notas de prensa que "corroboraban" la cifra
probablemente citaban todas la misma nota original, no tres lecturas
independientes del DOF — corroboración de prensa no es lo mismo que
lectura del documento primario. **La prensa sirve para localizar la
resolución (su código DOF), nunca como fuente en la base.**

Corregido para este ADR: se descargó el HTML real
(`dof.gob.mx/nota_detalle.php?codigo=5784426&fecha=09/04/2026`) con `curl`
y se leyó directamente — sin resumen intermedio de ninguna herramienta de
búsqueda — hasta encontrar el punto resolutivo exacto.

## Qué se descartó del reconocimiento original, y por qué

- **India + tubería de acero (`7305.11.02`):** la tasa de 81.61 USD/t es
  de **Welspun Corp**; las 15 partidas del corpus son de **BHARAT
  MERCANTILE EXPORTS PVT LTD**, un exportador distinto. La tasa que les
  tocaría (la residual "las demás") no estaba verificada en el
  reconocimiento. Queda `NEEDS_VALIDATION`.
- **China + aluminio para cocinar (`7615.10.02`):** una sola partida del
  corpus, y la cifra citada ("hasta 7.73 USD/kg") salía de una nota de
  Milenio, no de una resolución primaria abierta. Queda `NEEDS_VALIDATION`.
- **Las otras 18 combinaciones del corpus** (de las 21 identificadas)
  siguen `NEEDS_VALIDATION`: se verifican cuando el cable funcione de
  punta a punta, no antes — verificar las 21 antes de tener quien las lea
  habría repetido el patrón del FIX (dato cargado, nadie lo consulta).

## Decisión (Persona 1, 6-oct)

**Sólo avanza:** `CN` + cable de acero (14 partidas del corpus, proveedor
único `ORIENTAL TECHNICAL SUPPLY CO. LTD.`), de punta a punta —
RAW → PARSED → tabla → Espejo → medición, con este ADR.

### 1. Fuente primaria verificada

**RESOLUCIÓN final del procedimiento administrativo de examen de
vigencia de la cuota compensatoria impuesta a las importaciones de cables
de acero originarias de la República Popular China, independientemente
del país de procedencia.** Expediente EC 32-24. Publicada DOF 2026-04-09
(`codigo=5784426`). Firmada Ciudad de México, 2026-03-19.

Puntos citados verbatim:

> **213.** Se declara concluido el procedimiento administrativo de examen
> de vigencia de la cuota compensatoria impuesta a las importaciones de
> cables de acero originarias de China, independientemente del país de
> procedencia, que ingresan a través de las fracciones arancelarias de la
> TIGIE 7312.10.01, 7312.10.05, 7312.10.07 y 7312.10.99, **o por
> cualquier otra**.
>
> **214.** Se prórroga la vigencia de la cuota compensatoria... de 2.58
> dólares por kilogramo... por cinco años más, contados a partir del **17
> de diciembre de 2024**.
>
> **216.** ...los importadores... no estarán obligados a su pago si
> comprueban que el país de **origen** de la mercancía es distinto a
> China.

Tres cosas que este texto decide, no nosotros:

- **La cuota sigue al origen + la mercancía, no a la fracción listada**
  ("o por cualquier otra" — punto 213). `fraction_code` guarda las 4
  fracciones TAL COMO las lista la resolución, sin armonizar contra
  ningún otro catálogo: César corrigió varios de estos cables a
  `73121005` en otra tabla, pero si la cuota sigue a la mercancía o a la
  fracción lo decide este texto, no una armonización nuestra. Una
  partida de origen China en una fracción NO listada aquí no está
  cubierta por esta tabla — `NEEDS_VALIDATION`, no "no aplica".
- **Vigencia con término fijo**: 2024-12-17 a 2029-12-17. A diferencia de
  `ExchangeRate` (vigencia abierta que se cierra con la fila siguiente),
  aquí la propia norma declara cuándo termina.
- **Sin exportador nombrado**: una sola tasa para todo origen China. No
  hay "las demás" porque no hay ninguna tasa particular de la que ser "las
  demás" — es simplemente la única tasa que existe.

### 2. Modelo de datos

`regulatory.compensatory_duties` (migración `88cd0fb12273`), mismo patrón
que `fraction_nom_requirements` (ADR 0003): clave natural
`(origin_country, fraction_code, exporter_name, valid_from)` + vigencia +
procedencia, sin lógica en la tabla.

```
origin_country   VARCHAR(2)   NOT NULL  -- ISO-2, el ORIGEN, no procedencia
fraction_code    VARCHAR(8)   NOT NULL  -- tal como la lista la resolución
exporter_name    TEXT         NULL      -- NULL = sin distinción, o "las demás"
rate             NUMERIC(18,6) NOT NULL
rate_currency    VARCHAR(3)   NOT NULL
rate_unit        VARCHAR(8)   NOT NULL  -- "KG", tal como la resolución
scope_note       TEXT         NULL
  UNIQUE (origin_country, fraction_code, exporter_name, valid_from)
```

**Exportador — decidido:** `exporter_name` nullable, `NULL` = "todas las
demás" (cuando SÍ existe una tasa nombrada en otra fila) o "sin distinción"
(cuando, como aquí, no existe ninguna). Se cruza con
`operational.suppliers.legal_name`, que ya existía — sin columna nueva en
`operational`. **Sólo coincidencia exacta normalizada** (mayúsculas,
espacios, puntuación colapsados vía
`database.repositories.compensatory_duties.normalizar_nombre`) — nunca
aproximada: darle a alguien la tasa más baja de un exportador nombrado
porque el nombre se parece sería inventar una exención.

`operational.pedimento_items` gana `cc_amount`/`cc_amount_currency`, mismo
patrón que `igi_amount`/`vat_amount`: `NULL` = no consta en el documento.

### 3. Ingesta (RAW → PARSED → DATABASE)

`ingestion.se.cuotas_compensatorias.cable_de_acero_china()` — los valores
verificados a mano contra el texto primario (no hay HTML tabular que
extraer: cada cuota compensatoria es su propia resolución en prosa libre).
`ingestion.se.load.cargar_cuotas_compensatorias()` — idempotente por la
clave natural. `ingestion.se.cli --cable-acero-china` — RAW primero
(`raw.fetch`/`store_raw_bytes`/`verify_stored`, mismo contrato que
`ingestion.dof.cli`/`ingestion.banxico.cli`).

**El `content_hash` de esta página NO es estable entre descargas** —
verificado: dos descargas en días distintos (2026-10-06 y 2026-10-07)
dieron tamaños (483 547 vs 483 506 bytes) y hashes distintos
(`4f586487...` vs `adc93735...`), aunque el texto de los puntos 213/214
es idéntico en ambas. La página `nota_detalle.php` del DOF mezcla el
documento legal (estático) con un widget de indicadores del día
("Tipo de Cambio y Tasas al [fecha de hoy]") que cambia diariamente —
`content_hash` demuestra "este HTML se descargó de esta URL en esta
fecha", no "el texto legal no cambió byte a byte entre dos descargas".
Para demostrar eso haría falta normalizar el HTML antes de hashear
(quitando el widget dinámico), que este ADR no hizo — queda como
`NEEDS_VALIDATION` menor, no bloquea la carga de hoy.

### 4. Consumidor (Espejo)

`DivergenceType.COMPENSATORY_DUTY_MISMATCH` (`CRITICAL`, misma categoría
que `VALUE_MISMATCH`/`IGI_RATE_MISMATCH`: cambia lo que se paga).
`ExpectedItem.compensatory_duty_applies: bool | None` — `None` = no se
sabe (default: sólo una combinación verificada), `True` = sí, NUNCA
`False` (no se ha verificado lo suficiente para afirmar que una
combinación no tiene cuota — eso exigiría conocer TODAS las resoluciones
reales).

**Hallazgo real descubierto al construir el comparador, no anticipado en
el reconocimiento:** las 14 partidas del corpus declaran el cable en
**metro lineal** (clave "3" del Apéndice 7), y la cuota está fijada **por
kilogramo**. No se inventa un factor de conversión peso/metro — el
comparador emite el hallazgo igual ("falta declarar la cuota") pero sin
monto numérico exacto (`compensatory_duty_amount = None`), con el texto
explicándolo. `_cuota_compensatoria_esperada` en
`apps/api/routers/pedimentos.py` implementa esta distinción completa,
incluido el cruce por exportador.

### 5. Medición (antes/después, `apps.evaluacion.deteccion_26`)

| | antes | después (sin corregir medición) | después (con `condiciones_sembradas`) |
|---|---|---|---|
| TP | 48 | 48 | 48 |
| FP | 0 | **10** | 0 |
| FN | 6 | 6 | 6 |
| precisión | 100% | 82.76% | 100% |

**Confirmado, como anticipó Persona 1:** de las 14 partidas, **10 estaban
limpias** en el ground truth (sin ningún error sembrado) y pasaron a
producir un hallazgo cierto — mismo patrón exacto que el #200
(`_fracciones_que_un_dictamen_contradice`, ya documentado en
`apps/evaluacion/deteccion_26.py`: un hallazgo cierto no es un falso
positivo). Las otras 4 ya tenían otro evento sembrado (3×`WRONG_VALUE`,
1×`MISSING_TECHNICAL_FIELD`) y no se movieron de columna.

Corregido en el mismo PR: `_cuotas_compensatorias_ciertas()` en
`apps/evaluacion/deteccion_26.py`, mismo criterio que sus dos funciones
hermanas — lee de `CompensatoryDuty` VIGENTE, no de una lista de partidas
escrita a mano, así que sigue una cuota real nueva sin que nadie la
actualice.

## Consecuencias

- Cuatro bugs/correcciones reales encontrados en esta tarea, documentados
  en su lugar: (1) la fuente citada no decía lo que se afirmaba —
  corregida con lectura primaria directa; (2) la unidad de la partida no
  coincide con la de la cuota — no se inventa conversión; (3) 10 falsos
  positivos nuevos en `deteccion_26` — corregidos con
  `condiciones_sembradas`; (4) ninguno de los otros 20 combos
  origen+fracción del corpus se toca todavía.
- `exporter_name`/`normalizar_nombre` quedan listos para la PRÓXIMA cuota
  que sí distinga por exportador (India/Welspun, diferida) sin cambio de
  esquema.
- 18 combinaciones del corpus (de 21) siguen `NEEDS_VALIDATION` — ninguna
  fila sin consumidor posible, mismo criterio que Apéndice 8.

## Siguiente

Que Persona 1 decida si abre la verificación de las 18 combinaciones
restantes, acotando cada una a su propia resolución primaria (nunca
prensa) antes de proponer su fila.
