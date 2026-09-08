# Tarea Persona 3 — Cerrar el RAG e integrarlo

> Estado verificado el 8 de septiembre de 2026, 15:20, contra `develop` (e68683b)
> y la base compartida (alembic `4f2e5479db69`).

Ulises: tus siete pantallas están construidas y el #45 está bien planteado. Lo
que sigue es cerrarlo y conectarlo.

## Tarea 1 — Desatascar el #45 (5 minutos)

CI: **Lint y formato = FAILURE**, todo lo demás en verde.

```bash
ruff format . && ruff check --fix .
git commit -am "style: formato" && git push
```

Es lo mismo que me pasó a mí hoy: escribir código después de la última corrida
de `ruff format`. CI lo atrapa y la máquina local no.

## Tarea 2 — Integrar con `core/evidence` (ya está desbloqueado)

Dijiste: *«Este módulo no toca `core/evidence`. Avísame cuando lo cierres y lo
integro.»* **Ya está cerrado**, en el PR #43 (mergeado):

- `Evidence.data_origin` es campo nuevo y **obligatorio** en `LEGAL_SOURCE`
- `is_legal_basis` exige dos cosas: el tipo correcto **y** un origen real
- `LEGAL_BASIS_ORIGINS` = los cinco menos `SYNTHETIC`
- `SyntheticLegalBasisError`, separado de `NotLegalBasisError`
- `legal_source(data_origin=...)` es obligatorio y **sin valor por omisión**

También cambié `legal_refs` de tupla a un modelo:

```python
from core.evidence import LegalRef

LegalRef(
    document_ref=DocumentRef(...),
    valid_from=date(2018, 6, 25),
    content_hash="sha256:...",
    data_origin="OFFICIAL",
    valid_to=None,          # NULL = vigente
)
```

La tupla se fue porque al añadirle `data_origin` quedaban dos cadenas
adyacentes intercambiables sin que nada fallara: el hash en el origen y el
origen en el hash. Y entonces `data_origin` sería un sha256 —que nunca es
`"SYNTHETIC"`— así que la comprobación nueva no habría disparado jamás.

**Lo que te toca:** que `recuperar()` produzca `LegalRef` a partir de tus
chunks, y que `classify_product(legal_refs=...)` los reciba. Ese es el cable
que falta para que una clasificación llegue a ser defendible.

Tu salvaguarda y la mía se refuerzan: tú descartas lo `SYNTHETIC` al recuperar,
y si algo se cuela, el contrato lo rechaza al fundamentar. Dos capas, a
propósito — igual que tu filtro temporal.

## Tarea 3 — `ChunkStore` sobre pgvector

`rag/memoria.py` es en memoria. pgvector lleva semanas instalado sin usarse.

Tu puerto ya existe, así que es implementarlo. Dos cosas que no se pueden
perder al pasar a SQL:

1. **El filtro temporal en el `WHERE`.** Tu test del almacén descuidado a
   propósito es exactamente el que hay que hacer pasar aquí.
2. **`data_origin` por chunk**, no por índice.

## Tarea 4 — Cuando Brandon cargue el corpus

Le mandé el contrato que fijaste: `valid_from`/`valid_to` **por chunk**, y el
aviso de que tu fixture reproduce la estructura pero su texto no está
verificado, así que no sirve para cargar.

Cuando aterrice, tu pipeline debería ser ejecutar y ya.

---

## Después (no ahora)

- **Knowledge Graph** sobre Neo4j — encendido y vacío desde hace semanas.
- **Que la bandeja de revisión humana alimente Ground Truth.** Las correcciones
  que registre una persona son el activo más valioso del sistema; hoy se
  guardan pero no cierran el ciclo de evaluación. Coordínalo con Brandon
  cuando él tenga `ground_truth_records` andando.

---

## Definition of Done

Tests, type hints, logs estructurados, manejo explícito de error, trazabilidad
de fuentes, sintéticos marcados, sin secretos.

Un PR por tarea, contra `develop`. Reporta con el formato del §46.

Antes de reportar estado: `git fetch --prune && gh pr list`.
