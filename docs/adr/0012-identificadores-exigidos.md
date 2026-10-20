# ADR 0012 — Qué identificadores exige una operación

- **Fecha:** 2026-10-13
- **Estado:** aceptado (2026-10-13)
- **Decide:** Persona 1
- **Carga:** Persona 2 (tarea 4 del encargo del 13-oct)
- **Consume:** el Espejo (`core/shadow/compare.py`), ya implementado
- **Contexto de:** `docs/RECONOCIMIENTO_APENDICE_8.md` (6-oct)

## Contexto

El §20 pide que el Espejo compare identificadores. La comparación existía
(`required_identifiers` en `ExpectedItem`), pero siempre en `None`: el
catálogo del Apéndice 8 dice qué claves existen, no cuáles exige cada
operación.

El 6-oct se decidió **no** crear la tabla de reglas porque los 16 pedimentos
del corpus son clave `A1` y ninguna regla estructurable aplica a `A1`: habría
sido una tabla sin lector. Eso cambia ahora por dos motivos:

1. El generador sintético (tarea 1 de Persona 2) tiene que producir el
   escenario `WRONG_IDENTIFIER` del §25, y necesita saber en qué forma se
   escribe una regla.
2. El reconocimiento ya dijo qué cabe y qué no. No se modela a ciegas.

## Decisión

### 1. `regulatory.pedimento_identifier_requirements`

| Columna | Qué es |
|---|---|
| `identifier_code` | La clave del Apéndice 8 («V1») |
| `identifier_level` | `G` (se declara en el pedimento) o `P` (en la partida). **Obligatorio**: sin saber dónde se declara no se puede comprobar |
| `condition_kind` | `PEDIMENTO_KEY`, `FRACTION` o `NICO` |
| `condition_value` | La clave del Apéndice 2, la fracción de 8 dígitos, o fracción+NICO juntos (10) |
| `scope_note` | El «Supuesto de aplicación» íntegro |

Con vigencia y procedencia, como cualquier tabla de `regulatory`. Clave natural
`(identifier_code, condition_kind, condition_value, valid_from)`.

**Sólo lo estructurable:** las categorías (a) —10 claves que dependen de la
clave de pedimento— y (c) —`ME` y `VT`, que dependen de fracción/NICO— del
reconocimiento. Las ~130 que dependen de hechos del despacho (candado,
despacho anticipado…) **no se cargan**: no hay campo que las capture, y una
regla que nadie puede evaluar no es una regla. Las ~20 de programas
(IMMEX, PROSEC, tratados) tampoco, hasta que exista un campo «programa» en el
pedimento (sigue sin abrirse, como se decidió el 6-oct).

### 2. `operational.pedimentos.identifiers`

JSONB, `{}` por omisión, igual que `pedimento_items.identifiers`. Son los
identificadores de nivel `G`. Hasta ahora no había dónde declararlos.

### 3. Cómo los usa el Espejo

- `database/repositories/identificadores.py::cargar_reglas` lee lo vigente
  **una vez por pedimento**; `None` si no hay ninguna regla.
- Se comprueba **lo declarado**: si el documento declara la clave V1 o la
  fracción 9803.00.01, tiene que declarar el identificador que eso exige. Si la
  fracción declarada está mal, eso lo dice `FRACTION_MISMATCH`; no se mezcla.
- Nivel `P` → `ExpectedItem.required_identifiers`, contra
  `DeclaredItem.identifiers`.
- Nivel `G` → `ExpectedItem.required_document_identifiers`, contra
  `DeclaredItem.document_identifiers` (se repite en cada línea, como el tipo de
  cambio).
- **Mismo tipo, `IDENTIFIER_MISMATCH`**, en los dos niveles, para que la
  medición del §26 siga siendo un mapeo 1:1 con `WRONG_IDENTIFIER`. Lo que
  distingue al del pedimento es `field = "document_identifiers"`.
- El Panorama lo cuenta **una vez por pedimento** (`CAMPOS_DEL_DOCUMENTO` en
  `dashboard.py`), y el Espejo de la consola ya agrupa sólo lo que se repite
  igual en todas las partidas (#224).

### 4. Qué significa cada valor

| `required_*` | Significado |
|---|---|
| `None` | No hay reglas cargadas: **laguna**, la comprobación no cuenta |
| `()` | Hay reglas y ninguna aplica: no exige ninguno **de los estructurables** |
| `("V1",)` | Exige V1 |

`()` no dice «no exige ningún identificador». El ADR lo deja escrito porque es
la diferencia entre comprobar y aparentar que se comprobó.

## Para la carga (Persona 2)

- Una fila por (clave, condición). Si una clave aplica a dos claves de
  pedimento, son dos filas.
- Si el Apéndice 8 no dice el nivel de una clave (10 de 178 filas no lo
  traen), esa clave **no se carga** y se dice en el reporte: `NEEDS_VALIDATION`.
- Fuente: el Anexo 22 ya almacenado en RAW. Nada sin pasar por RAW.

## Para el generador sintético (§25)

`WRONG_IDENTIFIER`: un pedimento con una clave de la categoría (a) —o una
partida con la fracción/NICO de `ME`/`VT`— al que se le quita el identificador
que la regla exige. El ground truth (§26) apunta a la partida; para uno de
nivel `G`, a cada partida del pedimento, porque el Espejo lo registra en cada
una.

## Con los datos de hoy

No cambia nada visible: la tabla está vacía y la laguna se mantiene, ahora con
un texto que dice lo que falta de verdad.

## La carga (19-oct)

Persona 2 hizo el trabajo de fondo en el #242 (13-oct) y Persona 1 lo
rehízo sobre esta tabla (`--apendice8-requisitos` del CLI del DOF):

- **9 reglas, no 10**, todas de nivel `G` y `condition_kind = PEDIMENTO_KEY`.
  `TD` exige la clave **K1**, no `TD` (el reconocimiento del 6-oct se
  equivocaba); `AF` no nombra ninguna clave y no se carga.
- El «Supuesto de aplicación» de esas claves **no estaba cargado** en
  `pedimento_identifiers` (son las filas que el parser del 6-oct no pudo
  leer). Por eso cada regla se comprueba al cargar contra el texto del PDF
  crudo de MinIO (`verificar_contra_el_documento`): si la frase «clave de
  documento X» no aparece en la fila del identificador, la regla no se carga.
  La ventana acaba en la fila siguiente, para que la frase de la regla vecina
  no valide una falsa.
- `ME` y `VT` (categoría c, por fracción/NICO) quedan para otra carga.

Con el corpus actual (16 pedimentos `A1`) ninguna regla aplica: el Espejo pasa
de «no se sabe» a «ninguno de los estructurables», que es la respuesta correcta.
