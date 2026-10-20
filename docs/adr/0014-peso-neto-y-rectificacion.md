# ADR 0014 — Peso neto por partida y rectificación de pedimentos

- **Fecha:** 2026-10-13
- **Estado:** aceptado (2026-10-13, Persona 1) — pendiente mergear por
  `make merge` cuando el CI termine en verde.
- **Decide:** Persona 1
- **Pide:** Persona 1 (hoy, tarea del generador sintético §24: "el peso de
  cada partida, para que la cuota compensatoria pueda llevar importe" y
  "rectificaciones (§10)").

## Contexto — dos columnas aditivas, no una tabla nueva

Las dos faltas que esta tarea destraba son independientes entre sí, pero
las dos son condición para que el generador sintético (§24) pueda producir
escenarios completos. Se documentan juntas porque las dos son columnas
aditivas `nullable` sobre tablas que ya existen (mismo criterio que
`pedimento_identifiers.label`/`supuestos_de_aplicacion`, 6-oct) — ninguna
justifica una tabla propia.

### 1. `pedimento_items.net_weight_kg`

El ADR 0009 (cuota compensatoria del cable de acero) ya tropezó con esto y
lo dejó como hallazgo sin monto: la cuota está fijada por kilogramo
(`rate_unit="KG"`, 2.58 USD/kg) pero las partidas de cable del corpus
declaran en **metro lineal** (`commercial_unit`), y no hay ningún campo
que diga cuántos kilogramos pesa esa partida. Sin él, `cc_amount` no se
puede calcular — sólo se puede señalar que la cuota aplica.

`net_weight_kg` es un campo real del Anexo 22 (peso neto por partida), no
inventado: simplemente nunca se había modelado porque ninguna partida
cargada hasta ahora lo necesitaba para auditar un importe. `NULL` = no
consta, nunca 0 — mismo criterio que `cc_amount` (ADR 0009) y que toda
columna de dinero de este esquema: la ausencia no es un valor.

**No lleva columna de unidad hermana** (al contrario que `_amount`/
`_currency`): el kilogramo es la única unidad que tiene sentido para este
campo — es monetariamente "KG" siempre, no una moneda que varíe por fila.

### 2. `pedimentos.rectifies_pedimento_id` + `rectification_number`

§10 del maestro lista "rectificaciones" entre los datos sintéticos a
generar; hoy no existe ningún campo que relacione un pedimento con el que
rectifica. Modelo mínimo: autorreferencia nullable + número de secuencia.

- `rectifies_pedimento_id`: `NULL` en el original; en una rectificación,
  apunta al original. `ondelete="RESTRICT"` — un original referenciado no
  se borra.
- `rectification_number`: `NULL` en el original; `1`, `2`... en sus
  rectificaciones sucesivas.

**No se modela qué CAMBIÓ entre el original y la rectificación** como
columnas propias (p. ej. "campo_rectificado"): eso ya lo contesta comparar
fila contra fila entre `PedimentoItem` del original y el de la
rectificación — una tabla de diffs sería redundante con datos que ya están
en las dos filas.

## Opciones consideradas (rectificación)

**(a) Autorreferencia en `Pedimento`.** Elegida — mismo patrón que
cualquier jerarquía simple en este Canonical Model, sin tabla nueva.

**(b) Tabla `pedimento_rectifications` aparte, con su propio ciclo de
vida.** Descartada por ahora: no hay ningún dato adicional de la
rectificación en sí (fecha de rectificación, motivo) que el corpus vaya a
traer todavía — `Pedimento.operation_date` de la fila rectificadora ya es
esa fecha. Si en el futuro se necesita un motivo estructurado o un estado
de aceptación, es un ADR aparte con datos reales que lo pidan.

## Consecuencias

- Migración `67e3c2617b54` (additiva, sin tocar filas existentes).
- El generador sintético (`synthetic/`) puebla `net_weight_kg` cuando la
  partida declara mercancía sujeta a cuota compensatoria por peso, y puede
  producir un par (original, rectificación) para el escenario de
  rectificaciones del §10.
- Probado sólo contra mi Postgres local. Aprobado por Persona 1 (13-oct)
  — queda mergear por PR con `make merge` en cuanto el CI termine en
  verde; la base compartida la aplica Persona 1.
