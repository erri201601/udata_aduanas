# ADUANERO OS — Estado del proyecto y backlog

**Actualizado:** 2026-09-07  
**Mantiene:** Persona 1 (Erick)

Documento de contexto. Sirve para poner al día a cualquiera —persona o agente—
sin tener que leer el historial de conversaciones. Si algo aquí contradice a
`docs/00_ADUANERO_OS_PROMPT_MAESTRO.md`, manda el maestro.

---

## 1. Qué es esto

ADUANERO OS es una capa de inteligencia para comercio exterior mexicano.
No es un clasificador arancelario: es un motor que entiende mercancías,
las clasifica aplicando las Reglas Generales de Interpretación, y **sustenta
cada decisión con evidencia verificable hasta la fuente jurídica y su
vigencia**.

La prueba de si una funcionalidad está terminada son las diez preguntas del
§49 del maestro: qué detectaste, por qué, con qué regla, con qué fuente, qué
versión de esa fuente, cuándo era vigente, qué dato usaste, cuánta confianza,
cuánto dinero, si requiere revisión humana.

El objetivo inmediato es un MVP demostrable ante **AJR**, con fuentes
jurídicas reales y datos operativos sintéticos.

---

## 2. Dónde está todo

### Repositorio

| | |
|---|---|
| GitHub | `github.com/erri201601/udata_aduanas` — **privado** |
| Rama por defecto | `develop` |
| Flujo | `main` ← `develop` ← `feature/<tarea>` |
| Clon en el dev server | `/home/udata/Documentos/udata_aduanas` |

⚠️ Existe `/home/udata/Documentos/aduanas` con el scaffold original.
**Está obsoleto. Nadie debe trabajar ahí.**

`main` no tiene protección de ramas (GitHub la cobra en repos privados). Es
acuerdo de equipo: **nadie hace push directo a `main` ni a `develop`**.

### Dev server

La laptop de Persona 1, `udata-nitro`. Se accede **sólo por Tailscale**.

| Servicio | Puerto | Notas |
|---|---|---|
| API (FastAPI) | `100.86.182.104:8080` | servicio systemd `aduanero-api` |
| PostgreSQL 16 + pgvector | `100.86.182.104:5433` | **no 5432** |
| Neo4j | `:7474` (browser) · `:7687` (bolt) | vacío, sin usar |
| Redis | `:6379` | sin usar |
| MinIO | `:9000` (API) · `:9001` (consola) | buckets `aduanero-raw`, `aduanero-docs`, **vacíos** |

⚠️ **En el puerto 5432 hay un PostgreSQL nativo de OTRO proyecto**
(`Conta_inteligente/Tzol_Udata`). No se toca ni para leer.

Cada puerto se publica dos veces: en `127.0.0.1` y en `${TEAM_BIND_ADDR}` (la
IP de Tailscale). Nunca en `0.0.0.0`.

### Tailnet

`udata.com.mx`. Tres nodos: `udata-nitro` (100.86.182.104), `carlos`
(100.68.22.56), `yayo` (100.86.224.19).

### Operación

```bash
make test              # pytest
make lint              # ruff + mypy
make smoke             # verifica los 4 servicios (22 comprobaciones)
make backup            # respalda y verifica la restauración
make service-restart   # ⚠️ tras mergear cualquier PR que toque apps/api/
make service-logs
```

**El servicio de la API no recarga solo.** Después de mergear un PR que toque
`apps/api/`, hay que reiniciarlo o el equipo sigue viendo la versión anterior
sin ningún error que lo delate.

Respaldos: timer systemd diario a las 03:00, en `~/backups/aduanero/`, con
verificación de restauración en cada corrida. Viven en el mismo disco que la
base — copiarlos fuera sigue siendo manual.

---

## 3. Estructura del código

```
apps/api/            FastAPI. config.py · logging.py · main.py · routers/health.py
apps/web/            React + TypeScript + Vite (25 archivos)
core/evidence/       Evidence Contract        ✅ 6 módulos
core/rgi_engine/     RGI Engine               ⏳ en PR #8
core/llm/            ModelProvider            ✅ 10 módulos
core/prompts/        loader versionado        ✅
core/product_dna/    motor de extracción      ❌ VACÍO
core/classification/ orquestador              ❌ VACÍO
core/taxation/       Money Finder             ❌ VACÍO
core/audit/          Audit Engine             ❌ VACÍO
core/shadow/         Pedimento Espejo         ❌ VACÍO
core/opportunity/    Opportunity Finder       ❌ VACÍO
database/models/     23 entidades SQLAlchemy  ✅
database/migrations/ 2 migraciones aplicadas  ✅
database/seeds/      canonical_v0_1.py        ✅ (incompleto, ver §6)
schemas/             contratos Pydantic       ✅
ingestion/snice/     LIGIE/NICO               ❌ VACÍO ← el hueco más grande
rag/  graph/  synthetic/                      ❌ VACÍOS
tests/               13 archivos, 177 tests   ✅
.github/workflows/ci.yml                      ✅ 6 jobs
infrastructure/scripts/  backup.sh · restore.sh · smoke_test.sh · 00_INSTALACION.md
docs/                ver §9
```

### Base de datos — 23 tablas aplicadas, 0 filas de negocio

```
regulatory     legal_sources · legal_documents · legal_rules ·
               tariff_fractions · nicos · regulatory_events
operational    clients · suppliers · products · invoices · invoice_items ·
               coves · pedimentos · pedimento_items · synthetic_scenarios
intelligence   product_dnas · product_attributes · evidence_records ·
               classification_decisions · classification_candidates ·
               risk_findings · opportunity_findings · ground_truth_records
raw            (landing de ingestión, sin tablas todavía)
```

---

## 4. CI — seis jobs en cada PR

`.github/workflows/ci.yml`, se dispara en PR hacia `develop` o `main`.

| Job | Qué verifica |
|---|---|
| `lint` | `ruff check` + `ruff format --check` |
| `types` | `mypy`, descubriendo objetivos en tiempo de ejecución |
| `test` | `pytest` en **Python 3.12** contra PostgreSQL + pgvector real |
| `migrations` | `upgrade → downgrade → upgrade` + deriva modelos↔migraciones |
| `web` | `tsc` + `build`; se salta si no existe `apps/web/package.json` |
| `hygiene` | sin `.env`, sin credenciales, sin artefactos generados |

**Python 3.12 es obligatorio**: es lo que corre el dev server. Desarrollar en
3.13 o 3.14 rompe el pipeline.

El CI informa pero **no bloquea el merge**. A veces no se dispara solo; se
fuerza con `gh pr close <n> && gh pr reopen <n>`. Conviene revisar el consumo
de Actions en *Settings → Billing*.

---

## 5. Reglas no negociables

Están completas en `CLAUDE.md` y en el maestro. Las que más se violan:

1. **No inventar fundamento jurídico.** Toda afirmación legal apunta a una
   fuente almacenada con `source_id`, documento, artículo, fecha, vigencia y
   `content_hash`.
2. **No inventar fracciones.** Sin información suficiente:
   `INSUFFICIENT_INFORMATION` o `HUMAN_REVIEW_REQUIRED`.
3. **`data_origin` obligatorio**, con cinco valores cerrados: `OFFICIAL`,
   `PUBLIC`, `LICENSED`, `SYNTHETIC`, `HUMAN_VALIDATED`.
4. **`SYNTHETIC` nunca se presenta como real.** En la UI, badge
   `SYNTHETIC DEMO DATA`.
5. **Versionado temporal.** Nunca evaluar una operación histórica con
   regulación posterior. `valid_to = NULL` significa vigente; jamás se inventa
   una fecha de fin.
6. **El dinero es determinista.** `Decimal` y `NUMERIC`, nunca `float`. El LLM
   explica un resultado ya calculado; jamás lo calcula.
7. **Nunca saltarse RAW.** `SOURCE → RAW → PARSED → NORMALIZED → VALIDATED →
   DATABASE`. El crudo va a MinIO con su `content_hash` antes de parsear.
8. **Cambios de esquema sólo por Alembic**, aprobados por Persona 1.
9. **Ningún SDK de proveedor fuera de `core/llm/providers/`.**
10. **`core/` no importa la capa de persistencia** (§29). Devuelve dicts
    planos; quien escribe la fila ensambla.

Si algo no se puede verificar: `NEEDS_VALIDATION`, `UNKNOWN`,
`SOURCE_NOT_AVAILABLE`, `HUMAN_REVIEW_REQUIRED`. Si hace falta cambiar un
contrato central: **detenerse** y marcar `ARCHITECTURE_DECISION_REQUIRED`.

---

## 6. Qué está construido

### `core/evidence/` — Evidence Contract ✅

Qué debe llevar una evidencia para que una decisión sea defendible.

```
kinds.py      EvidenceKind + campos obligatorios por tipo
types.py      Evidence, DocumentRef, to_record_fields()
builder.py    constructores que hacen imposible la evidencia incompleta
contract.py   assert_legal_basis · assert_temporal_validity · assert_defensible
questions.py  Dossier — las diez preguntas del §49, ejecutables
errors.py     IncompleteEvidenceError, EvidenceOutOfValidityError, …
```

Cinco tipos, **sólo uno es fundamento jurídico**:

| Tipo | ¿Fundamento? |
|---|---|
| `LEGAL_SOURCE` — norma recuperada | **sí, el único** |
| `MODEL_OUTPUT` — lo produjo un modelo | no |
| `DETERMINISTIC` — regla de código | no |
| `HUMAN` — persona validó | no por sí solo |
| `COMPARABLE` — CBP CROSS, EBTI, WCO | **nunca** |

Uso:

```python
from core.evidence import builder, contract, questions

ev = builder.model_output(
    summary="El voltaje 220V aparece en la ficha técnica.",
    model_provider=meta.model_provider,
    model_name=meta.model_name,
    prompt_id=meta.prompt_id,
    prompt_version=meta.prompt_version,
    confidence=Decimal("0.92"),
)
fila = ev.to_record_fields()  # dict plano
```

**Deuda:** `evidence_records` no tiene columna `evidence_kind`. Hoy el tipo se
proyecta sobre `created_by` (16 chars), que no distingue `LEGAL_SOURCE` de
`COMPARABLE`. Requiere migración de Persona 2. Ya aprobada, pendiente.

### `core/rgi_engine/` — RGI Engine ⏳ PR #8, en verde

Máquina de evaluación de las Reglas Generales de Interpretación.

```
states.py    RGIStatus: RESOLVED | CONTINUE | INSUFFICIENT_INFORMATION |
             HUMAN_REVIEW_REQUIRED   (CONTINUE es interno, nunca se persiste)
ports.py     TariffCatalog · LegalNotes · Interpreter  ← puertos inyectados
context.py   ClassificationContext, ProductFact, TariffCandidate
results.py   RGIResult, ClassificationTrace
rules.py     RGI1 · RGI2 · RGI3A · RGI3B · RGI3C · RGI4 · RGI5 · RGI6
engine.py    classify()
```

Dos etapas: RGI 1→5 determinan la **partida**, RGI 6 desciende a **fracción**.

**No toca la base ni llama a ningún modelo.** Toda consulta al catálogo lleva
`on_date` obligatorio.

RGI 2, 4 y 5 no están implementadas pero **no se saltan**: detectan sus
precondiciones y escalan a `HUMAN_REVIEW_REQUIRED`.

**No resuelve NICO** (llega a 8 dígitos). **`specificity` la aporta el
catálogo**: si Persona 2 no la puebla, la RGI 3 a) no distingue nada.

### `core/llm/` — ModelProvider ✅

`generate` · `generate_structured` · `embed` · `analyze_image`. Adaptadores
OpenAI, Anthropic, Gemini, hueco Local. Salida estructurada validada con
Pydantic y reintento. `core/llm/canonical.py` mapea telemetría al Canonical
Model.

### `database/` — Canonical Model ✅

23 entidades, mixins componibles, enums como `VARCHAR + CHECK`
(`native_enum=False`), dinero `NUMERIC(18,6)` + columna de divisa,
`TIMESTAMPTZ` siempre, fracciones como `VARCHAR`.

`AIDecisionMixin` lleva telemetría de LLM (nullable, con CHECK condicional) y
`requires_human_review` con **default `true`**: el sistema falla hacia la
cautela.

### `apps/web/` — Frontend base ✅

React + TS + Vite. Pantalla de estado contra `/health/ready`. Layout de las 7
pantallas del §32 con badge `SYNTHETIC DEMO DATA` desde el inicio. Cliente TS
generado desde `/openapi.json` con `npm run gen:api`.

---

## 7. Qué falta

### Estado contra el scorecard del §44

```
DATA           0 de 14   ⛔ ninguna fuente jurídica extraída. MinIO vacío.
CORE           2 de 4    Evidence ✅ · RGI ⏳ · Product DNA ❌ · Classification ❌
SIMULATOR      0 de 8    synthetic/ vacío
INTELLIGENCE   1 de 6    Shadow ❌ Audit ❌ Money ❌ Opportunity ❌ Sentinel ❌ Graph ❌
PRODUCT        0.5 de 3  dashboard en layout · Copilot ❌ · demo AJR ❌
```

### El vertical slice del §42 — dónde se rompe

```
ficha técnica → Product DNA → RGI → Classification → Evidence →
pedimento sintético → Shadow → divergencia → Money Finder
       ❌            ⏳          ❌            ✅          ❌
```

**Los dos eslabones que faltan para tener algo demostrable son Product DNA
(el motor) y el Classification Orchestrator.**

---

## 8. Backlog por persona

### Persona 2 — Brandon (Data Engineer)

**Rama:** `brandon` · **Sin trabajo pendiente de integrar.**

| # | Tarea | Estado |
|---|---|---|
| 1 | **LIGIE/NICO, capítulos 84 y 85** | 🔴 **en curso — la prioridad del proyecto** |
| 2 | Columna `evidence_kind` en `evidence_records` | aprobada, pendiente |
| 3 | Ley Aduanera, RGCE 2026, Anexo 22 | pendiente |
| 4 | Generador sintético + Ground Truth (§24, §26) | pendiente |
| 5 | DOF Regulatory Watcher | Sprint 6 |

**Sobre la tarea 1:** SNICE aprobado como fuente, con distinción obligatoria —
para NICO es *la* fuente; para la tarifa es **complementaria**, el instrumento
jurídico es la LIGIE del DOF. `source_document` debe registrar el instrumento
y `source_url` de dónde se leyó.

Empezar por capítulos **84 y 85** (mayor volumen de importación, más ricos en
NICO, donde ocurren las disputas reales). Criterio para pasar al resto:
reporte de reconciliación que cuadre, 20 fracciones verificadas a mano,
cero campos inventados, RAW en MinIO con `content_hash`.

**Debe leer `core/rgi_engine/ports.py`** antes de terminar el parser: define
qué necesita el motor de un `TariffCatalog` y de `LegalNotes`. Y poblar
`specificity`, o la RGI 3 a) no desempata.

### Persona 3 — Ulises (AI + Full Stack)

**Rama:** `ulises` · **8 commits sin integrar, sin PR abierto.**

| # | Tarea | Estado |
|---|---|---|
| 0 | Abrir PR de los 8 commits pendientes | 🔴 primero |
| 1 | Extender el seed con `INFERRED` y `MISSING` | pequeño, va antes que el router |
| 2 | **Product DNA Engine v0.1** | ← **el orden correcto es este, no la pantalla** |
| 3 | Multimodal (imágenes, fichas escaneadas) | pendiente |
| 4 | `apps/api/db.py` — engine + sessionmaker + `get_session` | **SÍNCRONO**, ver abajo |
| 5 | Router de lectura + pantalla de Product DNA | después del motor |
| 6 | RAG jurídico (§27) — pgvector sin usar | pendiente |
| 7 | Evidence UI (§49) | depende del Evidence Contract ✅ |
| 8 | Human review UI · Knowledge Graph · Copilot | Sprint 6-7 |

**Sobre la 4:** la capa de sesión debe ser **síncrona**. No hay una sola línea
async en el repo — `apps/api/routers/health.py`, `tests/test_canonical_model.py`
y `database/seeds/` usan `Session` con `psycopg`. Meter `AsyncSession` crearía
dos mundos y los errores de greenlet al mezclarlos son de los peores de
diagnosticar. Requisitos: engine único a nivel de módulo con
`pool_pre_ping=True`, `expire_on_commit=False`, dependencia que cierre siempre
con rollback explícito, URL desde `apps.api.config`. Migrar el health check al
engine compartido (hoy crea uno desechable por llamada).

**Sobre la 2:** el Product DNA Engine es el **primer eslabón del §42**. La
pantalla sin él sólo muestra fixtures. Cada atributo declara su origen —
`OBSERVED` / `EXTRACTED` / `INFERRED` / `MISSING` — y el RGI Engine los trata
distinto: un hecho `INFERRED` baja la confianza de la clasificación. **El test
más importante: un dato ausente produce `MISSING`, no un valor plausible.**

### Persona 1 — Erick (Tech Lead)

| # | Tarea | Estado |
|---|---|---|
| — | Mergear PR #8 (RGI Engine) | verde, pendiente |
| — | Correr el seed contra la base compartida | decidido, pendiente |
| 1 | **Classification Orchestrator** (§9.2) | ← siguiente, **espera `apps/api/db.py`** |
| 2 | Money Finder (§9.5) — `Decimal`, determinista | sin dependencias, se puede adelantar |
| 3 | Pedimento Espejo (§9.3) | pendiente |
| 4 | Audit Engine (§9.4) | pendiente |
| 5 | Opportunity Finder (§9.6) | pendiente |

---

## 9. La siguiente tarea

**Product DNA Engine v0.1 — Persona 3.**

Es el primer eslabón del vertical slice y el único que bloquea todo lo demás:
sin él no hay nada que clasificar, el RGI Engine no tiene entrada real, y la
demo para AJR no existe.

En paralelo, **LIGIE/NICO de Persona 2** es igual de urgente por otra razón:
el RGI Engine ya está construido pero no tiene tarifa contra la que operar.

Cuando ambas existan, **Classification Orchestrator** (Persona 1) une las
piezas y el vertical slice queda cerrado de punta a punta.

---

## 10. Documentos del repositorio

| Archivo | Qué contiene |
|---|---|
| `docs/00_ADUANERO_OS_PROMPT_MAESTRO.md` | documento rector, 49 secciones |
| `docs/01_PERSONA_1_TECH_LEAD.md` | rol y responsabilidades de P1 |
| `CLAUDE.md` | reglas no negociables para agentes |
| `docs/ACCESO_EQUIPO.md` | credenciales y reglas de inserción |
| `docs/TAREA_P2_CANONICAL_MODEL.md` | especificación del Canonical Model |
| `docs/TAREA_P3_MODEL_PROVIDER.md` | especificación de ModelProvider y frontend |
| `docs/PROMPT_P2.md` · `docs/PROMPT_P3.md` | prompts de arranque para los agentes |
| `docs/ER_DIAGRAM.md` | diagrama Mermaid del modelo |
| `docs/adr/0001-puertos-y-bind-del-dev-server.md` | por qué 8080 y 5433 |
| `infrastructure/scripts/00_INSTALACION.md` | instalación del dev server |

---

## 11. Formato de reporte obligatorio (§46)

Al terminar cualquier tarea:

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
