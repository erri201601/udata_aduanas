# CLAUDE.md — ADUANERO OS

Instrucciones para agentes de código (Claude Code / Codex) en este repositorio.

## Antes de programar

Lee `docs/00_ADUANERO_OS_PROMPT_MAESTRO.md` y el documento del rol que te
corresponda. Después inspecciona el repositorio real: **no asumas que una
carpeta, tabla o función existe** (§35 y §47 del maestro).

Trabaja sólo dentro del alcance de la tarea. No reconstruyas arquitectura ya
definida ni reescribas módulos fuera del encargo.

## Reglas no negociables

1. **No inventes fundamento jurídico.** Toda afirmación legal apunta a una
   fuente almacenada, con `source_id`, documento, artículo, fecha de
   publicación, vigencia y `content_hash`.
2. **No inventes fracciones arancelarias.** Sin información suficiente, devuelve
   `INSUFFICIENT_INFORMATION` o `HUMAN_REVIEW_REQUIRED`.
3. **`data_origin` obligatorio** en todo dato relevante, con uno de estos cinco
   valores exactos: `OFFICIAL`, `PUBLIC`, `LICENSED`, `SYNTHETIC`,
   `HUMAN_VALIDATED`. No se crean valores nuevos sin aprobación de Persona 1.
4. **`SYNTHETIC` nunca se presenta como real.** En la UI se marca
   `SYNTHETIC DEMO DATA`.
5. **Versionado temporal.** Nunca evalúes una operación histórica con
   regulación posterior. Filtra siempre por
   `valid_from <= fecha_operación AND (valid_to IS NULL OR valid_to >= fecha_operación)`.
6. **El dinero es determinista.** `Decimal`, nunca `float`. El LLM explica un
   resultado ya calculado; jamás lo calcula.
7. **Nunca saltarse RAW.** El pipeline es
   `SOURCE → RAW → PARSED → NORMALIZED → VALIDATED → DATABASE`.
8. **Cambios de esquema sólo por Alembic.** Nada de DDL manual en PostgreSQL.
9. **Sin secretos en el código ni en Git.** Sólo `.env`, que está ignorado.
10. **Nada de SDK de proveedor dentro de `core/`.** Todo LLM pasa por la
    abstracción `ModelProvider` (§29 del maestro).

## Cuando no sepas algo

No asumas ni inventes. Marca explícitamente:
`NEEDS_VALIDATION`, `UNKNOWN`, `SOURCE_NOT_AVAILABLE`, `HUMAN_REVIEW_REQUIRED`.
Si hace falta cambiar un contrato central, detente y marca
`ARCHITECTURE_DECISION_REQUIRED`.

## Particularidades de este dev server

- **La API usa el puerto 8080**, no 8000: el 8000 está ocupado por otro proyecto.
- **PostgreSQL del proyecto usa 5433**, no 5432: el 5432 lo ocupa una instancia
  nativa ajena a ADUANERO OS. No la toques.
- Los servicios se publican en `BIND_ADDR` (por defecto `127.0.0.1`). Para dar
  acceso al equipo se usa la IP de Tailscale, **nunca `0.0.0.0`**.

## Comandos

```bash
source .venv/bin/activate
make test          # pytest
make lint          # ruff + mypy
make up            # docker compose up -d
make api           # uvicorn en 8080
alembic upgrade head
alembic revision --autogenerate -m "descripcion"
```

## Definition of Done

Una tarea no está terminada porque el código corra. Necesita: tests, type
hints, logs estructurados, manejo explícito de error, migración si toca la DB,
documentación mínima, trazabilidad de fuentes, datos sintéticos marcados y sin
secretos.

## Formato de reporte obligatorio (§46 del maestro)

Al terminar cualquier tarea, responde con:

```text
TAREA REALIZADA
ARCHIVOS MODIFICADOS
DECISIONES TÉCNICAS
PRUEBAS EJECUTADAS
RESULTADOS
RIESGOS
DEUDA TÉCNICA
DATOS/FUENTES UTILIZADOS
SIGUIENTE TAREA RECOMENDADA
```

## Git

Ramas: `main` ← `develop` ← `feature/*` | `fix/*` | `chore/*`.
Nadie trabaja en `main`. Un PR resuelve una tarea concreta. Persona 1 aprueba
cambios al Canonical Model y a los contratos.
