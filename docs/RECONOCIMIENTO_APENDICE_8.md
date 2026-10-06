# Reconocimiento — Apéndice 8 del Anexo 22: qué identificador exige cada operación

> Sin migración ni carga nueva. Sólo lectura del documento real + lo que ya
> está cargado, como pidió Persona 1 antes de decidir el esquema. 2026-10-06.

## Por qué este reconocimiento, y no una migración directa

`regulatory.pedimento_identifiers` (174 filas, 168 claves distintas —
6 repiten código con nivel G y P, p. ej. `CF`) ya tiene `code` y `level`,
cargados desde este mismo documento (PR #158). Lo que falta no es el
catálogo: es la REGLA de cuándo una operación exige cada clave. Hoy
`core/shadow/types.py` declara `required_identifiers: tuple[str,...] | None
= None` siempre, y el Espejo lo explica así:

> «no se conocen los identificadores que exige la operación: falta cargar
> el Apéndice 8 del Anexo 22»

Esa frase está **a medias desde antes de escribir una sola línea de código
nueva**: el catálogo de claves no dice cuáles exige una operación —nunca lo
dijo—, y cargarlo (ya hecho) no cerró el hueco. Antes de decidir un
esquema, hacía falta leer la columna que sí contesta la pregunta:
**"Supuestos de Aplicación"**, que nunca se cargó porque el layout de 6
columnas del PDF la mezcla con la fila siguiente sin separador confiable
(ver docstring de la migración `16368c5161d1`). Este documento la lee por
primera vez, con `pdftotext -bbox-layout` y el mismo motor de reparto por
programación dinámica que ya usa `ingestion/snice/tariff_headings.py`
(genérico: ancla por código, reparte líneas de una columna de texto).

**Advertencia de método, honesta:** la extracción de esta columna para
este reconocimiento es *best-effort*, no el parser verificado y probado
contra regresión que exigiría una carga real — por eso los conteos de
abajo llevan la palabra "aprox." donde corresponde, y todo lo que se cita
textualmente se verificó aparte, a mano, contra `pdftotext -layout` plano
(sin reconstruir nada). Cobertura de la extracción: **168 de 168** claves
con algún texto de "Supuestos de Aplicación" resuelto.

## Qué tiene la tabla real (6 columnas, no 2)

```
Clave | Nivel | Supuestos de Aplicación | Complemento 1 | Complemento 2 | Complemento 3
```

Ninguna de las 4 columnas de texto está cargada hoy. Dos cosas que hasta
ahora no se habían dicho en ningún documento:

1. **La Clave trae una ETIQUETA corta**, no sólo el código de 2 caracteres
   — p. ej. `CA- Candado electrónico.`, `DA- Despacho anticipado.`,
   `RA- Retorno de racks.`. Hoy `pedimento_identifiers` no tiene columna
   `label` — mismo hueco, mismo motivo (ambigüedad de columna), que
   `PedimentoClave.label` del Apéndice 2 (ver migración de esa tabla).
2. **Complemento 1/2/3** dicen qué VALOR declarar una vez que el
   identificador SÍ aplica (p. ej. para `CA`: "Número del Candado
   electrónico"). Son relevantes para una carga futura, pero no contestan
   la pregunta de este reconocimiento — cuáles exige una operación—, así
   que no se caracterizan más aquí.

## De qué depende "Supuestos de Aplicación" — la pregunta real

**No es `fracción → clave`.** Verificado leyendo las 168: la inmensa
mayoría de los supuestos describe un HECHO DE LA OPERACIÓN (qué régimen,
qué programa, qué trámite, qué tipo de mercancía, qué artículo o regla del
RGCE la ampara) — casi nunca una fracción arancelaria sola.

Cuatro patrones SÍ remiten a algo que el Canonical Model ya conoce o
podría conocer con un cambio chico. El resto, no.

### (a) Remiten a una CLAVE DE PEDIMENTO del Apéndice 2 — 10 claves, estructurable HOY

`A3`, `AF`, `TD`, `V1`, `V4`, `V5`, `V6`, `V7`, `V8`, `V9`. Texto real,
verbatim, de tres de ellas:

```
A3- Regularización de...   Identificar conforme a los supuestos de la
                            clave de documento A3 del apéndice 2.
TD- Tipo de desistimiento   Conforme a los supuestos de la clave de
                            documento TD del apéndice 2.
V1- Transferencias de...    Indicar conforme a los supuestos de la clave
                            de documento V1 del apéndice 2... y artículo
                            86 de la Ley.
```

`Pedimento.pedimento_key` (clave de documento/pedimento, Apéndice 2) ya
existe en el Canonical Model — este subconjunto es correlación
`identifier_code → pedimento_key`, mismo patrón exacto que
`fraction_nom_requirements` (ADR 0003): clave natural, vigencia,
procedencia, sin lógica en la tabla.

### (b) Remiten a un PROGRAMA/DECRETO — aprox. 20 claves, NO estructurable sin un campo nuevo

IMMEX aparece explícito en al menos 8: `DH`, `EB`, `GI`, `IM`, `MS`, `MT`,
`PV`, `ZC`. PROSEC en 1 (`PR`, "al amparo del PROSEC"). Tratados/decisiones
comerciales (T-MEC, TLCAELC, ALADI, TIPAT, ACE) en al menos 9: `AL`, `DT`,
`DU`, `ES`, `LR`, `NA`, `PP`, `ST`, `SU`. Texto real de `GI`:

```
GI- ...  Mercancía importada de forma temporal por empresas con Programa
         IMMEX al amparo del esquema de garantía a que se refiere el
         artículo 5, fracción IV del Decreto IMMEX.
```

**`Pedimento`/`PedimentoItem` no tienen ningún campo "programa" o
"decreto" hoy.** No es que falte cargar un catálogo: falta la COLUMNA.
Sin ella, esta correlación no se puede construir — es un
`ARCHITECTURE_DECISION_REQUIRED` aparte, no algo que este reconocimiento
pueda resolver solo.

### (c) Remiten a una FRACCIÓN/NICO explícitos — 2 claves, caso aparte

`ME` ("material de ensamble", exige NICO `9803.00.01` exacto) y `VT`
(lista 4 fracciones+NICO exactos: tipo y capacidad de vehículo). Son los
únicos 2 de 168 donde el supuesto SÍ es, literalmente, una fracción/NICO
— la excepción que confirma que Erick tenía razón al advertir que no es
el caso general.

### (d) El resto — aprox. 130 de 168, prosa libre sin campo que la capture hoy

La mayoría remite a una regla RGCE o un artículo de la Ley Aduanera
específicos (conteo aprox. por palabra clave: **45** mencionan
`regla N.N.N` o `artículo N` explícito en el texto capturado; es un piso,
no el total — la extracción corta algunas citas al envolver a
Complemento). Ejemplos reales, verbatim, elegidos para mostrar el rango:

```
CA- Candado electrónico.      Identificar el uso del Candado electrónico.
DA- Despacho anticipado.      Indicar que se trata de una operación de
                               comercio exterior que se sujeta a despacho
                               anticipado.
RA- Retorno de racks.         Indicar que se retornan racks que se
                               introdujeron a depósito fiscal con la
                               clave de pedimento F2.
XL- Presentación de...        Identificar la mercancía que se presenta en
                               vehículos con características
                               sobredimensionadas.
```

Ninguno de estos cuatro depende de fracción, programa o clave de
documento: depende de un HECHO DE PROCESO (¿hubo candado?, ¿fue despacho
anticipado?, ¿viene de depósito fiscal?, ¿el vehículo es
sobredimensionado?) que **ningún campo de `Pedimento`/`PedimentoItem`
modela hoy**, y que en varios casos el agente aduanal declara a partir de
información que no está en ninguna ficha técnica ni factura — es
conocimiento operativo del despacho, no un dato que un Product DNA pueda
inferir jamás.

## Cuántos caben en una tabla simple, y cuántos no

| Categoría | Aprox. | ¿Estructurable hoy? |
|---|---:|---|
| (a) clave de documento (Apéndice 2) | 10 | **Sí** — `identifier_code → pedimento_key`, patrón `fraction_nom_requirements` |
| (b) programa/decreto (IMMEX/PROSEC/TLC) | ~20 | No sin un campo nuevo en `Pedimento` (`program`/`decree`) |
| (c) fracción/NICO explícitos | 2 | Sí, pero como caso aislado — no justifica una tabla propia para 2 filas |
| (d) hecho de proceso / regla específica, sin campo | ~130 | No — ni con un campo nuevo: depende de información que el corpus no modela como dato estructurado en ningún lado |

**168 claves, y como mucho 12 (a+c, el 7%) caben hoy en una tabla
clave→condición al estilo del Anexo 2.4.1.** El resto no es "falta
cargarlo": es que el documento mismo define la condición en prosa, para
que la lea una persona o un sistema que entienda lenguaje natural — no
para que un `WHERE fraction_code = ...` la resuelva.

## Qué propongo (para que Erick decida, no una migración todavía)

1. **Cargar el texto completo de "Supuestos de Aplicación" (y la etiqueta
   corta de la Clave) en `pedimento_identifiers`** — columnas nuevas,
   nullable, aditivas, sin tocar `code`/`level`. Mismo criterio del ADR
   0002: cargar el texto primero, aunque la lógica de consumo venga
   después; sin esto, ni el 7% estructurable ni el resto tienen ningún
   lugar de donde un copiloto los cite. **Consumidor inmediato**: el RAG
   (`regulatory.legal_chunks`), igual que ya se hizo con partidas/
   subpartidas y con las reglas RGCE — el Apéndice 8 es tan norma citable
   como cualquier regla.
2. **Tabla nueva `regulatory.pedimento_identifier_requirements`** (patrón
   `fraction_nom_requirements`: clave natural
   `(identifier_code, pedimento_key, valid_from)`, vigencia, procedencia,
   sin lógica) — **sólo para las 10 claves de la categoría (a)**. Es el
   único subconjunto donde `required_identifiers` puede dejar de ser
   `None` con los datos que YA existen (`Pedimento.pedimento_key`), sin
   inventar nada ni esperar un cambio de esquema en otro lado.
3. **Marcar como `ARCHITECTURE_DECISION_REQUIRED` aparte, no resuelto
   aquí**: si vale la pena agregar un campo "programa"/"decreto" a
   `Pedimento` sólo para destrabar la categoría (b) (~20 claves,
   principalmente IMMEX). Antes de proponer esa columna hace falta saber
   si el corpus sintético y los pedimentos reales futuros van a traer ese
   dato en alguna parte — no se propone un esquema sin esa respuesta,
   mismo criterio que pidió Erick para no modelar en falso.
4. **La categoría (d) (~130 claves, el grueso) no entra a
   `required_identifiers` en esta ronda.** `required_identifiers` seguiría
   en `None` para toda operación cuya única fuente posible sean estas
   claves — exactamente la respuesta honesta, no una lista inventada de
   condiciones que el documento no formaliza como campo.

## Consumidor de este dato, antes de cargar nada (la lección del 5-oct)

- El texto de "Supuestos de Aplicación"/etiqueta: lo lee el RAG
  (`rag.chunking`/`ingestion.dof.load`, el mismo módulo que ya trocea
  RGCE) — Persona 2, en la misma carga.
- La tabla `pedimento_identifier_requirements` (10 filas): la lee
  `core/shadow/compare.py`, en el cableado de `required_identifiers` para
  las operaciones cuyo `pedimento_key` coincida — eso lo conecta quien
  corresponda según el mismo criterio que ADR 0003 ("Persona 1 o quien él
  designe"), no yo por mi cuenta.
- Si Erick no aprueba el campo "programa": la categoría (b) no se carga en
  ninguna tabla todavía — no hay fila sin consumidor posible.

## Decisión de Persona 1 (6-oct)

1. **Texto completo + etiqueta → SÍ.** Lector: el RAG/AduLex, como ya se
   hizo con RGCE. Implementado: `pedimento_identifiers.label`/
   `supuestos_de_aplicacion` (migración `d9fc5116df71`, nullable, aditiva)
   + un chunk de `regulatory.legal_chunks` por clave con ambos campos
   (`ingestion.dof.load.add_missing_identifier_text`/
   `load_identifier_chunks`, CLI: `ingestion.dof.cli --apendice8-texto`).
2. **Tabla `pedimento_identifier_requirements` (10 filas, categoría a) →
   NO POR AHORA.** Verificado contra el corpus: los 16 pedimentos
   sintéticos son 100% clave de documento `A1`; ninguna de las 10 claves
   de la categoría (a) (`A3`, `AF`, `TD`, `V1`, `V4`-`V9`) es `A1`.
   Diferido, con este dato escrito — no hay fila sin consumidor posible.
3. **ADR del campo "programa"/"decreto" (categoría b) → NO SE ABRE
   AHORA**, mismo motivo, con más fuerza: abrirlo sin saber si el corpus
   va a traer ese dato en alguna parte sería modelar en falso.
4. **Consecuencia correcta:** `required_identifiers` sigue en `None` para
   `A1`. No es un hueco por cerrar — es la respuesta honesta con los datos
   que hay.

## Resultado de la carga (6-oct): 2 hallazgos reales no anticipados

**172 claves distintas, 178 filas** (164→178: PR #158 cargó 174 filas/168
claves; esta carga corrigió un regex que nunca aceptaba guión largo y
agregó las 4 que se perdían). **168 de 178 filas con `label`+
`supuestos_de_aplicacion` completos** (162 claves distintas con cobertura
total; 16 filas sin texto son las 10 claves estructuralmente distintas de
la sección "Qué depende..." de arriba, que no traen columna "Nivel" ni
anclan al mismo modelo bbox — no es un hueco de parseo, es el documento).

1. **Guión largo ("–", U+2013) en vez de guión normal ("-", U+002D):**
   4 claves reales (`CR`, `EO`, `PB`, `PO`) nunca se cargaron en PR #158
   porque el regex original sólo aceptaba guión normal. Encontrado por
   validación cruzada al extraer "Supuestos de Aplicación" por
   coordenadas: aparecían claves bbox sin equivalente en el catálogo ya
   cargado. Mismo guión largo trae además una inconsistencia de formato
   adicional: en `EO`/`PO` el guión es una palabra bbox SEPARADA del
   código (dos tokens), no pegada como en `CR`/`PB` o el resto del
   documento — sin ese caso aparte, el label real salía con el guión
   colgando al frente ("– Emisor del certificado de origen.").
2. **6 claves repiten código con nivel `G` Y `P`, cada una con su propio
   supuesto** (`CF`, `EP`, `IF`, `SH`, `TB`, `ZL` — ya documentado en el
   docstring de `PedimentoIdentifier`, pero nunca antes verificado contra
   la extracción de texto). La primera versión de
   `parse_identifiers_con_texto` deduplicaba por `code` solo al combinar
   páginas — perdía en silencio la segunda mitad de cada una de las 6
   (p. ej. "CF- Registro..." nivel G se guardaba, "CF- Preferencia..."
   nivel P se descartaba). Corregido a `(code, level)`. El mismo defecto
   existía un nivel más arriba: `load_identifier_chunks` generaba el
   `article` del chunk sin el nivel, así que aunque la fila quedara
   completa en la tabla, la segunda mitad de las 6 claves igual se perdía
   al chocar contra la primera en el chequeo de idempotencia de chunks
   — corregido añadiendo `(nivel G/P)` al `article`.

Las dos fallas se encontraron ANTES de cargar nada a la base compartida
(verificadas contra el PDF real + pruebas de regresión antes del primer
`alembic upgrade`/backfill local) — ningún dato incorrecto llegó a
`shared`.
