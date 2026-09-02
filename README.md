# ADUANERO OS

Capa de inteligencia para comercio exterior mexicano. **UDATA.**

> Convertir información aduanera en decisiones trazables, explicables y
> económicamente accionables.

ADUANERO OS no es un clasificador arancelario. Es un motor que entiende
mercancías (Product DNA), las clasifica aplicando las Reglas Generales de
Interpretación, sustenta cada decisión con evidencia verificable, construye un
Pedimento Espejo, compara lo esperado contra lo declarado, detecta riesgos y
oportunidades, y calcula el impacto económico — todo con trazabilidad hasta la
fuente jurídica y su vigencia.

## Estado

**Sprint 0 — scaffold e infraestructura.** El Canonical Data Model, el RGI
Engine y el resto de motores aún no están implementados.

| Componente | Estado |
|---|---|
| Estructura del repositorio | ✅ |
| `docker-compose.yml` (Postgres+pgvector, Neo4j, Redis, MinIO) | ✅ levantado y verificado |
| FastAPI + health checks | ✅ |
| Alembic | ✅ inicializado y conectado, sin migraciones |
| Smoke test del stack | ✅ 20 comprobaciones |
| Canonical Data Model | ⬜ siguiente PR |
| Evidence Contract | ⬜ |
| RGI Engine | ⬜ |

## Requisitos

Python 3.12+, Docker + Compose v2, Node 20+ (para `apps/web`).
La instalación paso a paso está en
[`infrastructure/scripts/00_INSTALACION.md`](infrastructure/scripts/00_INSTALACION.md).

## Arranque

```bash
cp .env.example .env      # y rellena las contraseñas
docker compose up -d      # Postgres 5433 · Neo4j 7474/7687 · Redis 6379 · MinIO 9000/9001

python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
alembic upgrade head
make api                  # http://localhost:8080/docs

./infrastructure/scripts/smoke_test.sh   # verifica los 4 servicios
```

> **Puertos.** La API usa **8080** y PostgreSQL **5433**. En el dev server de
> Persona 1, los puertos 8000 y 5432 ya están ocupados por otros procesos.

## Estructura

```text
apps/api          FastAPI — API del núcleo
apps/web          React + TypeScript
core/             ADUANERO CORE — propiedad de UDATA, desacoplado de ANA/AJR
ingestion/        extractores por fuente (Persona 2)
rag/  graph/      RAG y Knowledge Graph (Persona 3)
synthetic/        generador de datos sintéticos y Ground Truth
database/         modelos SQLAlchemy, migraciones Alembic, seeds
schemas/          contratos Pydantic compartidos
prompts/          prompts versionados del producto
infrastructure/   Docker y scripts de operación
docs/             documentos rectores y ADRs
```

## Reglas del proyecto

Las no negociables están en [`CLAUDE.md`](CLAUDE.md) y, con todo el detalle, en
[`docs/00_ADUANERO_OS_PROMPT_MAESTRO.md`](docs/00_ADUANERO_OS_PROMPT_MAESTRO.md).
En resumen: no se inventa fundamento jurídico ni fracciones; todo dato lleva
`data_origin`; los datos sintéticos jamás se presentan como reales; el dinero se
calcula con `Decimal` en código determinista, nunca con el LLM; y ningún cambio
de esquema ocurre fuera de Alembic.

## Datos

Los datos operativos del MVP son **sintéticos** y están marcados como tales. Las
fuentes jurídicas (LIGIE, NICO, Ley Aduanera, RGCE, Anexo 22, DOF) son reales y
se versionan con su vigencia.

## Equipo

| | Rol | Ámbito |
|---|---|---|
| Persona 1 | Tech Lead · Product Owner · Integration | arquitectura, contratos, RGI, Shadow, Audit, Money Finder |
| Persona 2 | Senior Data Engineer | extracción, ETL, normalización, DOF Watcher, datos sintéticos |
| Persona 3 | Senior AI + Full Stack Engineer | Product DNA, RAG, Knowledge Graph, Copilot, frontend |

Los accesos para el equipo están en [`docs/ACCESO_EQUIPO.md`](docs/ACCESO_EQUIPO.md).

## Licencia

Propietario — UDATA. Todos los derechos reservados.
