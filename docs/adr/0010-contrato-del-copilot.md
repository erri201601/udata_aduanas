# ADR 0010 — El contrato del Copilot

- **Fecha:** 2026-10-13
- **Estado:** aceptado (2026-10-13)
- **Decide:** Persona 1
- **Implementa:** Persona 3 (tarea 2 del encargo del 13-oct)

## Contexto

El §31 del maestro pide que el Copilot conteste con esta estructura:

```json
{
  "answer": "",
  "confidence": 0.0,
  "sources": [],
  "evidence": [],
  "missing_information": [],
  "requires_human_review": false
}
```

Y, sin evidencia suficiente, con el texto literal «No tengo evidencia
suficiente en la base cargada.». Nunca inventar citas.

Hoy `POST /copilot/consultar` (`apps/api/routers/copilot.py`) **no redacta**:
devuelve los pasajes recuperados, con vigencia, procedencia y hash, y
`redacta_respuesta = false`. Esa decisión fue deliberada (parafrasear la ley es
como se producen las citas inventadas) y tuvo sentido mientras no hubo forma de
comprobar la redacción. Pero deja el §31 sin cumplir: no hay `answer`, ni
`confidence`, ni `missing_information`, ni `requires_human_review`.

## Decisión

**El Copilot cumple el §31.** Redacta, pero no aporta: el modelo explica los
pasajes que ya se recuperaron, y una comprobación determinista, que no es el
modelo, decide si la redacción se puede entregar.

### 1. Campos

Se **añaden** a `Respuesta`; no se quita ninguno de los actuales (la consola y
AduLex los usan).

| Campo | Qué es | De dónde sale |
|---|---|---|
| `answer` | La respuesta redactada, con cada afirmación citando un pasaje como `[n]` | El modelo, a través de `ModelProvider` |
| `confidence` | Entre 0 y 1 | **Calculada, no declarada por el modelo** (punto 4) |
| `sources` | Las fuentes de los pasajes **citados** en `answer`: `source_id`, documento, artículo, `valid_from`, `valid_to`, `url`, `content_hash` | Los chunks recuperados |
| `evidence` | Los pasajes recuperados: los `pasajes` actuales, con el índice `n` con el que se citan | `rag.recuperar` |
| `missing_information` | Lo que la pregunta necesita y los pasajes no traen | El modelo, más las ausencias deterministas del punto 5 |
| `requires_human_review` | Ver punto 6 | Calculado |
| `prompt_id`, `prompt_version` | El prompt con el que se redactó (§30) | `core.prompts` |

`pasajes` se conserva como alias de `evidence` mientras la consola migra.
`redacta_respuesta` pasa a decir si `answer` lo redactó el modelo en esta
consulta.

### 2. Sólo se redacta sobre lo que puede fundamentar

Al modelo se le pasan **sólo** los pasajes con `puede_fundamentar = true`
(vigentes en la fecha y con `data_origin` que fundamenta). Si no hay ninguno,
no se llama al modelo:

```
answer                 "No tengo evidencia suficiente en la base cargada."
confidence             0
sources                []
requires_human_review  true
```

El texto es literal, sin adornos ni variantes.

### 3. Las citas se comprueban, y la comprobación no es el modelo

El prompt (`prompts/copilot/answer.v0.1.md`) exige que cada oración de
`answer` termine con al menos una cita `[n]` a un pasaje entregado. Después, un
validador determinista (código, no LLM):

1. Extrae las citas de `answer`.
2. **Si alguna cita un `n` que no se entregó, la redacción entera se descarta**
   y se responde como si no hubiera evidencia, con
   `missing_information = ["La redacción citó un pasaje que no existe; se descartó."]`.
   No se corrige ni se recorta: una cita inventada invalida todo lo demás.
3. Cuenta las oraciones sin cita.

`sources` se construye **desde las citas válidas**, nunca desde lo que el
modelo diga que usó.

### 4. `confidence` no la declara el modelo

La confianza que un modelo se atribuye no está calibrada y no se puede medir.
Aquí es:

```
confidence = oraciones con cita válida / oraciones de answer
```

Redondeada a dos decimales. Es comprobable, y la evaluación del §39 (tasa de
respuestas sin sustento) mide lo mismo.

### 5. `missing_information` determinista

Además de lo que diga el modelo, se añade siempre que aplique:

- La búsqueda se degradó a término (`degradado_por` no nulo).
- La pregunta nombra un instrumento que **no está en `corpus_consultado`**
  (PROSEC, Regla 8ª, cupos…). La lista de instrumentos no cargados sale de
  `corpus_consultado`, no se escribe a mano.

### 6. `requires_human_review`

Es `true` si se cumple cualquiera de estas condiciones:

- No hubo evidencia (punto 2) o se descartó la redacción (punto 3).
- `confidence < 1`, es decir, alguna oración sin cita.
- `missing_information` no está vacía.
- El modelo no estuvo disponible (punto 7).

Por omisión es `true`. Pasar a `false` exige que se cumplan todas las
condiciones contrarias, igual que `AIDecisionMixin.requires_human_review`.

### 7. Sin modelo, no se finge

Sin llave, sin cuota o con error del proveedor, se devuelven los pasajes como
hoy y:

```
answer                 "Sin redacción: el modelo no está disponible. Los pasajes están en evidence."
redacta_respuesta      false
confidence             0
requires_human_review  true
degradado_por          <el motivo>
```

No se devuelve el texto de «sin evidencia», porque la evidencia existe; lo que
falta es la redacción.

### 8. Sin SDK en `core/`

Todo pasa por `ModelProvider` (regla 10 de `CLAUDE.md`). La llamada registra
`prompt_id`, `prompt_version`, modelo, tokens y latencia en el log
estructurado (§37).

## Tests que la implementación tiene que traer

- **Ninguna cita fuera de los pasajes recuperados.** Un proveedor de prueba
  que devuelve `[7]` con 3 pasajes entregados: la respuesta sale con el texto
  de «sin evidencia» y `requires_human_review = true`.
- **Sin pasajes que fundamenten no se llama al modelo.** Un proveedor que
  falla si se le llama.
- **`sources` sólo contiene lo citado.** 5 pasajes, el texto cita `[2]`: una
  fuente.
- **`confidence`** con una oración sin cita entre tres: `0.67` y revisión
  humana.
- **Proveedor caído:** punto 7, no el texto de «sin evidencia».

## Medición

La evaluación de la búsqueda jurídica del §39 (tarea 4 de Persona 3) mide
sobre este contrato la tasa de acierto, la precisión de las fuentes y la tasa
de respuestas sin sustento (`confidence < 1`).

## Lo que no cambia

- La recuperación (`rag.recuperar`), el filtro por vigencia y procedencia, y
  los contadores de descartes.
- AduLex sigue enseñando los pasajes. La redacción va **encima** de ellos, no
  en su lugar: quien lee tiene que poder comprobar cada `[n]` contra el texto
  de la norma.
