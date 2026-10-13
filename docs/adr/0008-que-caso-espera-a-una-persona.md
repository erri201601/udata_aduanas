# ADR 0008 — Qué caso espera a una persona

- **Fecha:** 2026-10-06
- **Estado:** propuesto (2026-10-06)
- **Decide:** Persona 1
- **Propone:** Persona 3
- **Medido por:** Persona 1, contra la base compartida (6 175 decisiones)

## Contexto

Tres partes del sistema contestaban «¿qué espera a una persona?», y cada una
lo hacía a su manera:

| Dónde | Criterio |
|---|---|
| `GET /review` (la bandeja) | `requires_human_review`, la última decisión de cada `product_dna_id`, **contando también los veredictos** en «la última» |
| `apps/evaluacion/preguntas_pendientes.py` | `status = 'HUMAN_REVIEW_REQUIRED'`, la última por `product_id`, y un filtro de «ya contestadas» que miraba sólo el lado de la tarifa |
| `_casos_que_preguntaban` (recálculo al contestar, #192) | **todas** las pendientes, no sólo la última |

Con tres conjuntos, una misma pregunta podía tener un número de casos en la
terminal, otro en la bandeja y otro distinto en lo que se recalculaba.

Y al medir contra la base compartida salió algo peor: **33 de los 90 casos de
la bandeja ya tenían veredicto de César** (30 con fracción y 3
FALTA_INFORMACION). El corpus se reclasificó después de sus veredictos, la
decisión nueva quedó como «la más reciente» y ningún veredicto apuntaba a ella.
Un tercio de la bandeja era trabajo ya hecho.

## La primera propuesta, y por qué no basta

Persona 3 propuso excluir los veredictos del «la última», para que un veredicto
sobre una decisión vieja (desde una pestaña abierta de antes) no escondiera la
decisión nueva de la misma ficha.

Se midió: ese hueco **no afectaba hoy a ningún caso**, y con esa definición
**los 33 seguían en la bandeja**. Seguía buscando el dictamen por decisión,
cuando el dictamen es sobre el caso.

## Decisión

**La unidad es el caso, y un caso es una ficha** (`product_dna_id`). Es lo que
se decidió el 5-oct para el tablero (`_ya_dictaminada` en
`apps/api/routers/dashboard.py`) y lo que el #213 puso en las mediciones.

```
vigente(ficha)   la última decisión con data_origin <> 'HUMAN_VALIDATED'
                 de ese product_dna_id
dictamen(ficha)  el último HUMAN_VALIDATED de ese product_dna_id, revise la
                 decisión que revise
pendiente        vigente.requires_human_review  Y  la ficha sin dictamen
```

- Un **FALTA_INFORMACION** también cierra el caso: pide un dato, no otra
  opinión.
- Si la ficha **cambia de versión**, es otro `product_dna_id` y otro caso:
  vuelve. El dictamen se pronunció sobre unos hechos que ya no son los que hay.
- Las decisiones **sin `product_dna_id`** pasan una a una: no hay caso al que
  agruparlas, y descartarlas perdería casos en silencio.
- **Sin página.** El límite de 50 de `GET /review` es una página, no parte de
  la definición.

Vive en `database/repositories/preguntas.py` y la usan la bandeja, el script de
preguntas y el recálculo al contestar. Las preguntas se leen tal cual las dejó
el motor en `rgi_trace[-1].preguntas`, sin filtro propio: decidir qué se
pregunta es del motor.

### La forma de la consulta

Medido por Persona 1 con `EXPLAIN` contra la base compartida:

| Forma | Tiempo | Casos |
|---|---|---|
| `max(created_at)` correlacionado + `NOT EXISTS` | 379 ms | 57 |
| `DISTINCT ON (product_dna_id)` en CTE + `NOT EXISTS` + `UNION ALL` | 11 ms | 57 |

Se usa la segunda. No necesita índice nuevo.

## Aceptación

Con los datos del 6-oct: **57 pendientes** (90 − 33). Tests de integración
para cada hueco, en `tests/test_pendientes_integracion.py`:

- un veredicto sobre una decisión vieja de la misma ficha → el caso no está
  pendiente;
- un recálculo posterior al veredicto → el caso sigue sin estar pendiente.

## Consecuencias

- La bandeja deja de enseñar trabajo ya hecho.
- El script de preguntas cuenta casos distintos, no filas: sus cifras pueden no
  coincidir con las citadas antes del 6-oct.
- Quedan **dos contadores con criterio propio**, fuera de este cambio:
  - `GET /dashboard`, `requieren_revision`: usa la vigente pero no mira el
    dictamen, así que con los datos de hoy diría 90 donde la bandeja dice 57.
  - `GET /metrics/classification`, `pendientes_de_revision`: cuenta todas las
    decisiones del motor con la bandera, también las históricas.

  Unificarlos con esta definición es la siguiente tarea natural; no se hace
  aquí porque el encargo nombraba tres consumidores.

  **Unificados el 7-oct.** Con la bandeja vacía —César había dictaminado los
  57 casos— el tablero decía **33** y la pantalla de precisión **4 610**. Los
  dos cuentan ahora con `pendientes()`, y
  `tests/test_contadores_de_pendientes.py` comprueba contra Postgres que los
  tres números se mueven igual (con el código anterior: `[1, 2, 4]` donde debía
  ser `[1, 1, 1]`).
