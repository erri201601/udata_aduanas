# ADR 0004 — Niveles intermedios de un guion en la nomenclatura

- **Fecha:** 2026-09-30
- **Estado:** aceptado (2026-09-30)
- **Decide:** Persona 1
- **Pregunta de:** Persona 2 — Persona 1 encontró el mismo hueco por su
  cuenta el 29/30-sep, desde el motor; este documento junta las dos
  mediciones (una desde el catálogo, otra desde una clasificación real que
  se niega) porque coinciden exactas y eso es señal de que el diagnóstico
  es sólido, no una coincidencia de medición.

## Contexto

### El caso que lo hace urgente (Persona 1, 30-sep, verificado en vivo)

```
TUBERIA DE ACERO AL CARBONO, ⌀ EXTERIOR 508 MM
declarada: 73051291

RGI 3a  →  elige la partida 7305 correctamente
RGI 6   →  «Varias subpartidas de 7305 comprenden la mercancía
           (730511, 730512, 730519, 730520, 730531, 730539, 730590)
           y ninguna es más específica. El motor no elige.»
```

El motor se niega **correctamente**: 730512 y 730531 tienen hoy este texto
en la base, y nada en él las distingue:

```
730512   «Los demás, soldados longitudinalmente.»
730531   «Soldados longitudinalmente.»
```

Lo que sí las distingue no está cargado. Verificado contra la página 7305
de la LIGIE real (`pdftotext -layout`, texto exacto, sin reconstruir nada):

```
73.05         Los demás tubos (por ejemplo: soldados o remachados) de
              sección circular con diámetro exterior superior a 406.4 mm,
              de hierro o acero.
    -         Tubos de los tipos utilizados en oleoductos o gasoductos:
7305.11  --   Soldados longitudinalmente con arco sumergido.
7305.12  --   Los demás, soldados longitudinalmente.
7305.19  --   Los demás.
7305.20  -    Tubos de entubación ("casing") de los tipos utilizados para
              la extracción de petróleo o gas.
    -         Los demás, soldados:
7305.31  --   Soldados longitudinalmente.
7305.39  --   Los demás.
```

Dos líneas llevan un **guion sin ningún dígito delante**:
`Tubos de los tipos utilizados en oleoductos o gasoductos:` y
`Los demás, soldados:`. No son partida ni subpartida — son el nivel que la
propia LIGIE usa para agrupar subpartidas hermanas bajo un encabezado
común, y sin él 730512 y 730531 son, literalmente, la misma pregunta sin
la mitad de la respuesta.

**Lo que hoy pasa con esas dos líneas**, verificado contra
`tariff_headings` de la base compartida: la primera quedó pegada al final
de la descripción de la propia partida `7305` (la contamina: 7305 ya no
dice sólo lo que 7305 dice); la segunda **no está en ninguna fila**, se
perdió. `ingestion/snice/tariff_headings.py` no tiene ningún concepto de
esto hoy — no reconoce el guion, sólo código y descripción.

### Por qué bloquea más de una cosa (§48, §49)

Mientras esto no esté cargado, el paso 3 del §48 («Clasifica HS/TIGIE/NICO»)
no puede cerrar en ninguna mercancía cuya subpartida tenga hermanas
repetidas, y con él quedan bloqueados el paso 7 (impacto económico) y la
pregunta 9 del §49 (¿cuánto dinero representa?) para esos mismos casos: sin
fracción no hay cuota que calcular.

### Cuánto pesa, medido dos veces — contra el catálogo y contra el motor

Medido el 30-sep contra `regulatory.tariff_headings` de la base compartida
(6 855 filas: 1 236 de 4 dígitos, 5 619 de 6):

| | |
|---|---|
| líneas de un solo guion sin código en todo el documento (`pdftotext -layout`) | **812** |
| grupos de subpartidas (6 dígitos) que repiten descripción textual idéntica entre hermanas, dentro de la misma partida | **511** |
| partidas de 4 dígitos afectadas por al menos un grupo así | **274** |
| filas de 6 dígitos dentro de algún grupo de texto repetido | **1 390** |
| veces que aparece exactamente `"Los demás."` en `tariff_headings` | **844** |
| veces que aparece exactamente `"Los demás."` en `tariff_fractions` (8 dígitos) | 1 455 |

Los cuatro números en negrita y el de 844 son los que citó Persona 1;
coinciden exactos con esta medición, hecha de forma independiente desde el
catálogo (Persona 1 los verificó desde el motor, contra un caso real). A
nivel de fracción (8 dígitos) no hay repetición de texto entre hermanas de
la misma subpartida directa (0 grupos) — el problema es específico del
nivel de 6 dígitos hacia arriba, que es justo donde vive el guion.

**Una sola profundidad de guion sin código en todo el documento:** se
comprobó `--` y `---` sin código y no aparece ninguna (0 en ambos casos).
Todas las líneas `--` en la LIGIE llevan su propio código de 6 dígitos — el
guion sin código es siempre de un solo nivel.

### Línea base del §26, para medir si la carga ayuda o empeora

`python -m apps.evaluacion.deteccion_26 --target shared`, corrido el
30-sep, sesión de sólo lectura:

```
AGREGADO  TP 47 · FP 0 · FN 8 · TN 126
  precision 100.00 · recall 85.45 · F1 92.15

POR TIPO (la que importa aquí)
  WRONG_FRACTION   TP 2 FN 5 · recall 28.57
```

Ésta es la foto de antes. El criterio de aceptación de abajo pide la misma
corrida después, y que ningún FP nuevo aparezca — no sólo que suba el TP.

## El contrato que cualquier opción tiene que respetar

`core/rgi_engine/ports.py` declara

```python
def subheadings(self, *, on_date: date, heading: str) -> Sequence[TariffCandidate]: ...
```

y `TariffCandidate` (`core/rgi_engine/context.py`):

```python
class TariffCandidate(BaseModel):
    code: str  # NUNCA nulo
    text: str
    level: (
        str  # "CHAPTER | HEADING | SUBHEADING | FRACTION | NICO" — cerrado, sin hueco para "grupo"
    )
    ...

    @property
    def chapter(self) -> str:
        return self.code[:2]

    @property
    def heading(self) -> str:
        return self.code[:4]
```

Un grupo de guion no tiene código real. Cualquier diseño que permita que un
grupo llegue a instanciar un `TariffCandidate` por sí solo — con un código
vacío, `None` o inventado — rompe `code: str` (tipo) o la regla 2 de
CLAUDE.md (nunca inventar una fracción/código), y además no tiene dónde
mapear en `level`, que es un enum cerrado que ninguno de los tres
consumidores del motor (RGI 3a, RGI 6, `_algo_la_sostiene`) sabe
interpretar si aparece un valor nuevo.

**La salida que no toca el contrato:** un grupo nunca se devuelve como
candidato. Vive sólo como ingrediente del `text` que la implementación del
repositorio construye para las subpartidas reales — exactamente la misma
idea que el ADR 0002 ya usó para concatenar partida › subpartida.
`subheadings()` sigue devolviendo únicamente `TariffCandidate` con `code`
real de 6 dígitos; lo único que cambia es que su `text`, donde exista
grupo, pasa de «partida › subpartida» a «partida › grupo › subpartida».

## Opciones consideradas

Persona 1 pidió comparar como mínimo tres. Se añade una cuarta.

### (a) Columna nueva en las filas de 6 dígitos, con el texto de su grupo padre

```sql
ALTER TABLE tariff_headings ADD COLUMN group_text TEXT NULL;
```

Poblada sólo en las ~1 390 filas de 6 dígitos que cuelgan de un guion sin
código; `NULL` en el resto.

- **Contrato (ports.py):** no lo toca. `code` sigue siendo siempre el de 6
  dígitos; el repositorio arma `text` leyendo `group_text` si existe.
- **Esquema:** aditiva, no toca `code`/`level`/los `CHECK` del ADR 0002.
- **Costo real:** el grupo no es una entidad — es texto repetido en cada
  hermana. Si una reforma del DOF cambia sólo el texto del grupo (no el de
  sus hijas), hay que tocar N filas a la vez, y `content_hash`/`source_id`
  dejan de identificar una fuente por dato: dos filas del mismo grupo
  podrían quedar con distinto `content_hash` si el backfill se corre en dos
  pasadas. Ningún `valid_from`/`valid_to` propio del grupo — hereda el de
  la subpartida, que no es necesariamente el mismo (el guion puede llevar
  más tiempo vigente que alguna de sus hijas, o viceversa).

### (b) Filas propias en `tariff_headings`, con código sintético y CHECK que lo distinga del real

```sql
ALTER TABLE tariff_headings ADD COLUMN is_synthetic_code BOOLEAN NOT NULL DEFAULT false;
-- código sintético, p. ej. "7305-1", "7305-2" (no es un código LIGIE real)
```

- **Contrato (ports.py):** **sí lo compromete**, y es el riesgo que hay que
  decir en voz alta. `headings()`/`subheadings()` hoy seleccionan de
  `tariff_headings` por nivel/rango de código; si esa consulta no filtra
  explícitamente `is_synthetic_code = false` en cada sitio donde se
  construye un `TariffCandidate`, un grupo puede colarse con un código
  inventado en `TariffCandidate.code`. Eso es exactamente el defecto que el
  ADR 0002 evitó al separar `tariff_headings` de `tariff_fractions`: ahí la
  garantía era "por construcción" (tablas distintas); aquí volvería a ser
  "por disciplina" (una bandera que hay que recordar filtrar en cada
  query), y el ADR 0002 ya documentó por qué eso no basta.
- **Esquema:** toca la tabla que el ADR 0002 definió con la garantía de
  "código siempre real"; la debilita.
- **Costo real:** el código sintético necesita una convención (¿qué pasa si
  dos guiones caen bajo la misma partida, se numeran "-1"/"-2"? ¿y si el
  DOF reforma el documento y el orden cambia?) que no existe hoy y que
  alguien tendría que mantener estable entre cargas para que
  `content_hash` y `valid_from` sigan identificando la misma fila entre
  una carga y la siguiente.

### (c) `parent_id` autorreferenciado en `tariff_headings`, con `code` nullable

```sql
ALTER TABLE tariff_headings
  ADD COLUMN parent_id UUID NULL REFERENCES tariff_headings(id),
  ALTER COLUMN code DROP NOT NULL;
-- level pasa a admitir un valor nuevo sin dígitos (¿0? ¿'DASH'?)
```

- **Contrato (ports.py):** mismo riesgo que (b), con un matiz: un `code`
  `NULL` que llegara a `TariffCandidate.code: str` sin filtrar sería un
  error de tipo en vez de un valor con apariencia válida — falla más
  ruidoso que (b), que es preferible si algo se escapa, pero sigue
  exigiendo que cada consumidor filtre `code IS NOT NULL` explícitamente
  antes de construir un candidato.
- **Esquema:** es el que más contratos existentes toca. `code NOT NULL` y
  `CHECK (length(code) = level)` son, con `level IN (4, 6)`, las dos
  garantías con las que el ADR 0002 sostiene que "un nodo de esta tabla
  nunca es un resultado de clasificación". Relajar `code` a nullable
  cambia esa invariante para las 6 855 filas que hoy sí la cumplen, no sólo
  para las nuevas. El modelo ORM (`TariffHeading.code: Mapped[str]`) pasa a
  `Mapped[str | None]`, y hay que auditar cada sitio que hoy asume que
  `code` siempre existe (cargadores, tests, el propio repositorio).
- **A favor, honestamente:** es la más parecida a cómo la LIGIE se lee de
  verdad — un solo árbol, un solo tipo de nodo — y evita una tabla extra.
  Si Persona 1 prefiere pagar el costo de auditoría a cambio de esa
  simplicidad conceptual, es una decisión legítima; este documento sólo
  dice que no es gratis.

### (d) Tabla nueva `regulatory.tariff_heading_groups` — no pedida, se añade

Mismo criterio que el ADR 0002: invariante distinta, tabla distinta.

```
regulatory.tariff_heading_groups
  id                 UUID        PK
  parent_heading_id  UUID        NOT NULL  FK -> tariff_headings.id
  ordinal            SMALLINT    NOT NULL  -- posición entre hermanos del mismo padre, sin código con qué ordenar
  description        TEXT        NOT NULL
  + RegulatoryMixin (valid_from/valid_to, data_origin, source_id,
    source_url, content_hash, published_at, retrieved_at)
  UNIQUE (parent_heading_id, ordinal, valid_from)

tariff_headings.group_id  UUID NULL  FK -> tariff_heading_groups.id   -- sólo en filas level = 6
```

- **Contrato (ports.py):** no lo toca, por construcción y no por
  disciplina: esta tabla no tiene columna `code` en absoluto (no es
  nullable, no existe), así que no hay forma de que un grupo llegue a
  `TariffCandidate.code` sin que alguien escriba explícitamente el código
  para hacerlo — no hay atajo accidental.
- **Esquema:** `tariff_headings` no cambia ni una línea: `code NOT NULL`,
  `CHECK (length(code) = level)`, `level IN (4, 6)` siguen exactamente como
  los dejó el ADR 0002. Sólo se añade la columna `group_id`, nullable,
  aditiva.
- **Trazabilidad:** el grupo tiene su propia vigencia y su propia fuente —
  si el DOF reforma sólo el texto del guion, es una fila, no N.
- **Costo real:** una tabla más, un JOIN más al construir `text` en el
  repositorio. `ordinal` es posicional, no arancelario — tiene que quedar
  documentado en el modelo que nunca debe tratarse como si fuera un código.

## Comparación de costo de contrato

| opción | toca `ports.py`/`TariffCandidate` | toca los `CHECK` del ADR 0002 | riesgo de fuga a `code` |
|---|---|---|---|
| (a) columna denormalizada | no | no | ninguno |
| (b) código sintético + flag | sí, por disciplina | sí (columna nueva, sin romper CHECK existentes) | real si algún query olvida el filtro |
| (c) `parent_id` + `code` nullable | sí, por disciplina | sí, directamente (`NOT NULL` se relaja) | real si algún query olvida el filtro, pero falla ruidoso |
| (d) tabla nueva | no | no | ninguno, por construcción |

## Recomendación de Persona 2

**(d)**, por lo mismo que el ADR 0002 ya razonó una vez: separar por
invariante evita depender de que nadie lo olvide. Si el costo de una tabla
más pesa más que esa garantía, **(a)** es la segunda opción — no toca el
contrato tampoco, a cambio de perder vigencia/trazabilidad independiente
del grupo, que hoy es un costo menor porque el documento no reforma el
guion solo casi nunca (no verificado con certeza; es una suposición, se
marca como tal).

## Criterio de aceptación (Persona 1, verbatim, verificable contra la base real)

1. La tubería PED_SIM_001-001 resuelve a la subpartida 730512, no se queda
   en `HUMAN_REVIEW_REQUIRED` por empate.
2. El motivo que escribe la traza cita el texto del nivel padre.
3. `python -m apps.evaluacion.deteccion_26 --target shared` sube
   `WRONG_FRACTION` por encima de 2 de 7 (recall > 28.57 %), sin que
   aparezca ni un falso positivo nuevo. Línea base de este documento:
   TP 47 · FP 0 · FN 8 · recall 85.45 % agregado, WRONG_FRACTION TP 2 FN 5.
4. Ninguna mercancía que hoy se niega (`HUMAN_REVIEW_REQUIRED` por empate)
   empieza a devolver una fracción equivocada. Se corre la medición antes y
   después y se comparan los falsos positivos, no sólo el recall agregado.

## Preguntas abiertas para Persona 1

1. **¿(a), (b), (c) o (d)?** Recomendación: (d), con (a) como alternativa
   si la tabla extra no se justifica. (b) y (c) quedan documentadas por
   pedirlo explícitamente, con su costo de contrato hecho explícito arriba.
2. Si es (d): ¿nombre `tariff_heading_groups` está bien, o se prefiere
   otro?
3. **¿`group_id`/el equivalente sólo en subpartidas de 6 dígitos, o también
   puede colgar directo una partida de 4?** No se encontró ningún caso real
   de un guion colgando directo de una partida de 4 dígitos sin pasar por
   una subpartida de 6, pero no se revisó el documento completo — sólo se
   midió por patrón de texto (`grep` sobre `pdftotext -layout`, no letura
   línea por línea de las 1 789 páginas).
4. **¿Backfill dirigido a las 274 partidas afectadas, o se espera al
   `--reset` general que ya está en la cola?** Recomendación: backfill
   dirigido — mismo patrón ya usado esta sesión (`add_missing_coves`,
   `add_fraccion_chunks_for_long_rules`), no depende de que el `--reset`
   general se autorice primero.

## Consecuencias si se acepta

- **Persona 2:** migración Alembic reversible, parser de
  `ingestion/snice/tariff_headings.py` reescrito para reconocer la línea de
  un solo guion sin código (hoy no tiene ningún concepto de esto) y
  emitirla como grupo en vez de perderla o pegarla a la fila vecina;
  backfill dirigido a las 274 partidas; tests unit del parser + un caso de
  integración con 7305 entero (fragmento real, ya verificado en este
  documento); pipeline completo sin saltarse RAW, `content_hash`,
  `data_origin`, vigencia por fila — igual que cualquier otra carga.
- **Persona 1 / motor de clasificación:** donde exista grupo,
  `TariffCatalogRepository` concatena «partida › grupo › subpartida» al
  construir `text` (mismo mecanismo del ADR 0002, un eslabón más). Si algo
  no se puede verificar contra la fuente, la fila no se carga y queda
  `NEEDS_VALIDATION` — no se infiere el padre por posición si el parser no
  lo ve con certeza.
- Después de esto, según el orden que fijó Persona 1: Anexo 2.4.1
  (fracción → NOM, ADR 0003, ya aceptado) y luego lo que quede.

## Decisión de Persona 1 (2026-09-30)

**Opción (d), con un cambio: identidad por `description_hash`, no por
`ordinal`.**

Confirma (d) por la razón de contrato (la de este documento) y por una más
fuerte: un grupo de guion es un registro regulatorio, y §13 exige que todo
registro lleve su propia fuente, su hash y su vigencia — (a) lo hubiera
convertido en texto repetido en 1 390 filas, sin poder contestar «¿desde
cuándo dice eso ese guion?» (§14), y `content_hash` habría dejado de
identificar un dato para identificar una copia.

**El cambio:** `UNIQUE (parent_heading_id, ordinal, valid_from)` como se
proponía tenía el mismo defecto que se le objetó a (b) — si el DOF inserta
un grupo nuevo a la mitad de una partida, los `ordinal` posteriores se
desplazan, y el mismo grupo de siempre aparecería con un `ordinal`
distinto sin que su texto cambiara. El esquema queda igual (`ordinal` sigue
en la tabla, sirve para ordenar y mostrar), pero la IDENTIDAD para recargar
es `(parent_heading_id, description_hash)`: si aparece el mismo hash bajo
el mismo padre con un `ordinal` distinto al ya guardado, es
`NEEDS_VALIDATION` — no se renombra sola. Implementado así en
`add_missing_heading_groups` (`ingestion.snice.load`).

**Aviso sobre la RGI 3a:** cuando el texto del grupo entre en la
concatenación que arma `TariffCatalogRepository`, puede cambiar qué
candidatas de PARTIDA cumplen una condición medible (la misma clase de
fuga que ya se documentó una vez en `core/rgi_engine/rules.py`, con la
tubería resolviendo a 73052001 en vez de negarse). El criterio de
aceptación 4 no es una formalidad: se corre `deteccion_26` antes y después
de conectar el repositorio, comparando falsos positivos, no sólo el TP
agregado.

**Pendiente, fuera de esta migración:** el cableado de
`TariffCatalogRepository`/`core/rgi_engine/rules.py` para que el texto del
grupo entre en `TariffCandidate.text` — el ADR 0002 lo asignó a Persona 1
("Persona 1 cambia `TariffCatalogRepository`..."), y este documento no lo
reasigna por su cuenta. La migración, el parser y el backfill dirigido
(274 partidas medidas, 1 024 grupos reales encontrados) quedan completos y
verificados en `feature/niveles-intermedios-guion`; el criterio de
aceptación 1-3 no se puede cerrar del todo hasta que ese cableado exista.
