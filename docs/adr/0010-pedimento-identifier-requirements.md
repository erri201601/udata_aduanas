# ADR 0010 — Qué clave de pedimento exige cada identificador del Apéndice 8

- **Fecha:** 2026-10-13
- **Estado:** propuesto — implementado en rama, pendiente de revisión de
  Persona 1 antes de mergear a `develop` o cargar a la base compartida.
- **Decide:** Persona 1
- **Pide:** Persona 1 (hoy, "qué identificadores exige cada operación —
  necesito una tabla con vigencia y fuente"), sobre el reconocimiento que
  Persona 2 ya había escrito el 6-oct (`docs/RECONOCIMIENTO_APENDICE_8.md`)
  y que en esa fecha se había diferido.

## Contexto

`docs/RECONOCIMIENTO_APENDICE_8.md` (6-oct) separó las 168 claves con
"Supuestos de Aplicación" cargado en 4 categorías, y encontró que sólo la
categoría (a) — 10 claves que remiten a una clave de documento concreta del
Apéndice 2 — es estructurable hoy sin inventar ningún campo nuevo. Esa
misma sesión decidió **no construir la tabla todavía**: los 16 pedimentos
del corpus sintético son 100% clave `A1`, y ninguna de las 10 claves de la
categoría (a) es `A1` — no había fila sin consumidor posible.

Hoy Persona 1 pide explícitamente la tabla, con vigencia y fuente, y se
compromete a hacer él mismo el cableado en el Espejo (`core/shadow`). Eso
resuelve la condición que faltaba el 6-oct — ya hay quien la lee — y es la
misma lección del 5-oct (ningún dato sin consumidor real) aplicada al
revés: aquí el consumidor ya está prometido, así que la carga puede
proceder.

## Dos correcciones sobre el reconocimiento del 6-oct, verificadas contra
## el texto real antes de escribir la migración

El reconocimiento listó `A3, AF, TD, V1, V4-V9` como las 10 claves
estructurables. Verificando cada una contra
`pedimento_identifiers.supuestos_de_aplicacion` (ya cargado, no un resumen):

1. **`TD` no exige la clave `TD`.** Su texto real: «Conforme a los
   supuestos de la clave de documento K1 del apéndice 2.» — exige `K1`, no
   `TD`. El reconocimiento citó la clave equivocada.
2. **`AF` no nombra ninguna clave concreta.** Su texto real: «Identificar
   el activo fijo, únicamente cuando la clave de documento no sea
   exclusiva para dicha mercancía.» Es una condición de EXCLUSIÓN sobre
   cualquier clave que no sea exclusiva para esa mercancía — no un
   `identifier_code -> pedimento_key` de uno a uno. Forzarla a una fila
   sería inventar la clave que el documento no da (§8.2 del maestro).

**Resultado: 9 filas, no 10.** De las 9, **8 son auto-referentes** — el
identificador `V1` exige la clave de documento `V1` (y así `A3`, `V4`...
`V9`) — y **1 es la excepción real** (`TD` -> `K1`). `AF` queda fuera,
sin tabla ni `NEEDS_VALIDATION` explícito: no hay fila que proponer sin
inventar.

## Opciones consideradas

**(a) Tabla nueva `regulatory.pedimento_identifier_requirements`, por
Alembic.** Mismo patrón que `fraction_nom_requirements` (ADR 0003): clave
natural `(identifier_code, pedimento_key, valid_from)`, vigencia,
procedencia, sin lógica en la tabla. **Elegida.**

**(b) Ampliar `pedimento_identifiers` con una columna `requires_pedimento_key`.**
Descartada por la misma razón que ADR 0003 descartó meter la NOM en
`tariff_fractions`: no es un escalar en general (aunque en este subconjunto
sí lo sea 1:1) y mezclaría "qué es la clave" con "qué exige", dos
preguntas distintas que ya viven en tablas distintas en este Canonical
Model.

**(c) Incluir también la categoría (c) (`ME`, `VT` — remiten a
fracción/NICO explícitos, no a una clave).** Descartada aquí: el propio
reconocimiento ya advirtió que 2 filas no justifican una tabla propia, y
mezclarlas con `pedimento_key` en la misma columna obligaría a un campo
polimórfico. Si Persona 1 las quiere, son un ADR aparte con su propia
columna.

## Decisión propuesta

**Opción (a)**, con el esquema de abajo, usando `RegulatoryMixin` +
`DataOriginMixin` completos (igual que toda tabla de `regulatory`):

```
identifier_code  VARCHAR(2)  NOT NULL   -- Apéndice 8, p. ej. "V1", "TD"
pedimento_key    VARCHAR(2)  NOT NULL   -- Apéndice 2, p. ej. "V1", "K1"
scope_note       TEXT        NULL       -- "regla 4.3.21. y artículo 86 de la Ley"
  UNIQUE (identifier_code, pedimento_key, valid_from)
  INDEX (pedimento_key, valid_from, valid_to)  -- lectura por clave de pedimento
```

**Vigencia y fuente:** las 9 filas comparten `valid_from = 2026-01-15`,
`source_url`/`source_document` del Anexo 22 RGCE 2026 (mismas constantes
que ya usa `ingestion.dof.load` para el resto del Apéndice 8/Anexo 22).
`published_at` queda `NULL` — ningún documento de este repo verifica la
fecha de publicación del Anexo 22 por separado de su vigencia (mismo hueco
ya documentado como deuda técnica para RGCE/Anexo 22 en
`docs/ESTADO_DEL_PROYECTO.md`; esta tabla no lo resuelve ni lo empeora).

**`AF` no se carga en ninguna tabla.** Si Persona 1 decide más adelante
que la condición de `AF` ("clave no exclusiva para la mercancía") merece
otra estructura — una columna booleana en `PedimentoClave`, por ejemplo —
es `ARCHITECTURE_DECISION_REQUIRED` aparte: este ADR no lo propone sin
saber qué dato real lo alimentaría.

**No se cablea `core/shadow`.** Persona 1 dijo que hace él la comparación
en el Espejo; esta tabla sólo pone el dato donde `required_identifiers`
pueda, por fin, dejar de ser `None` para las operaciones con clave `V1`,
`K1`, `A3`, `V4`-`V9` — hoy ninguna del corpus sintético (100% `A1`), pero
ya no por falta de la tabla.

## Implementado (rama `feature/identificadores-exigidos-apendice-8`, 13-oct)

- Modelo `PedimentoIdentifierRequirement`
  (`database/models/regulatory.py`), migración `5e25666ea028`.
- Datos verificados a mano, 9 filas, en
  `ingestion/dof/apendice_8_requisitos.py` (no un parser nuevo — ver el
  módulo para la cita verbatim de cada una).
- Loader `ingestion.dof.load.load_identifier_requirements`, idempotente,
  mismo patrón que `cargar_cuotas_compensatorias`. CLI:
  `ingestion.dof.cli --apendice8-requisitos`.
- Probado contra mi Postgres local únicamente (migración aplicada,
  9 filas cargadas, suite completa en verde). **No tocado:** la base
  compartida ni `develop` — pendiente de que Persona 1 revise este ADR y
  avise que se puede mergear/cargar, como pidió para toda la sesión de
  hoy.
