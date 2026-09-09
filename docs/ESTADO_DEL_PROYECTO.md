# ADUANERO OS — Estado del proyecto y backlog

**Actualizado:** 2026-09-09  
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
| MinIO | `:9000` (API) · `:9001` (consola) | `aduanero-raw` con 4 documentos; `aduanero-docs` vacío |

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
make lint              # ruff + ruff format --check + mypy
make merge PR=54       # mergea sólo si los seis jobs del CI pasaron
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
apps/api/            FastAPI, 17 endpoints    ✅ 9 routers
apps/web/            React + TS + Vite        ✅ 7 pantallas del §32
core/evidence/       Evidence Contract        ✅ 7 módulos
core/rgi_engine/     RGI Engine               ✅ 7 módulos
core/llm/            ModelProvider            ✅ 12 módulos
core/prompts/        loader versionado        ✅
core/product_dna/    motor de extracción      ✅
core/classification/ orquestador              ✅
core/taxation/       Money Finder             ✅
core/audit/          Audit Engine             ✅
core/shadow/         Pedimento Espejo         ✅
core/opportunity/    Opportunity Finder       ✅
core/review/         revisión humana          ✅
rag/                 RAG jurídico (§27)       ✅ 7 módulos, sin vectorizar
database/models/     29 entidades SQLAlchemy  ✅
database/migrations/ 9 migraciones aplicadas  ✅
database/repositories/  chunks · notes · tariff · classification · review
database/seeds/      canonical_v0_1.py        ✅ (ver deuda en §7)
schemas/             contratos Pydantic       ✅
ingestion/snice/     LIGIE · NICO · notas     ✅
ingestion/dof/       Anexo 22                 ✅
ingestion/diputados/ Ley Aduanera             ✅
ingestion/{anam,banxico,cbp_cross,datamexico,ebti,sat,vucem,wco}/   ❌ VACÍOS
synthetic/           generador sintético      ❌ sólo __init__.py
graph/               Knowledge Graph          ❌ sólo __init__.py
tests/               44 archivos, 593 tests   ✅
.github/workflows/ci.yml                      ✅ 6 jobs
```

### Base de datos — 29 tablas, corpus jurídico cargado

Alembic en `9877c9584a4c`. Conteos verificados el 9 de septiembre:

```
regulatory     legal_sources 4 · legal_documents 4 · legal_rules 366 ·
               legal_chunks 274 (0 vectorizados) · tariff_fractions 1,445 ·
               nicos 2,171 · customs_offices 127 · units_of_measure 22 ·
               pedimento_claves 66 · non_tariff_regulations 37 ·
               regulatory_events 0
operational    clients · suppliers · products · invoices · invoice_items ·
               coves · pedimentos · pedimento_items · synthetic_scenarios
               — 1 fila cada una, del seed
intelligence   classification_decisions 7 · classification_candidates 106 ·
               evidence_records 63 · product_dnas 1 · product_attributes 4 ·
               shadow_reviews 2 · risk_findings 1 · opportunity_findings 0 ·
               ground_truth_records 1
raw            sin tablas: el crudo vive en MinIO
```

Las 366 normas son `OFFICIAL`: 274 artículos de la Ley Aduanera y 92 notas de
Sección y Capítulo de la LIGIE. Los 1,445 aranceles son los capítulos **84**
(890) y **85** (555) — 2 de 97.

### RAW en MinIO — cuatro documentos con su hash

```
diputados/ley_aduanera_20251119.pdf
dof/anexo22_20260115.pdf
snice/ligie_unificada_20250728.pdf
snice/fracciones_20260420.xlsx
```

La regla 7 se cumple de punta a punta: nada de lo anterior se parseó sin que
el crudo estuviera antes en MinIO con su `content_hash`.

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

El CI informa pero **no bloquea el merge**: `develop` no está protegida y no
puede estarlo, porque la protección de ramas en repos privados exige plan de
pago. Por eso se mergea con **`make merge PR=NN`**, que comprueba los seis jobs
y se niega si alguno no está en `SUCCESS` — nunca con el botón de GitHub. Cinco
en verde y uno en rojo no es «casi verde», y una comprobación que no arrancó no
es una que pasó. A veces no se dispara solo; se
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

Los siete motores del maestro —Product DNA §16, RGI §18, Classification §19,
Pedimento Espejo §20, Audit §21, Money Finder §22 y Opportunity §23, sobre el
Evidence Contract §17— están completos y **alcanzables desde la API**. Esa
segunda mitad es la que faltaba hasta el 8 de septiembre: cuatro motores
existían, estaban probados, y ningún endpoint los invocaba.

### `core/evidence/` — Evidence Contract ✅

Qué debe llevar una evidencia para que una decisión sea defendible.

```
kinds.py      EvidenceKind + campos obligatorios por tipo
types.py      Evidence, DocumentRef, LegalRef, to_record_fields()
builder.py    constructores que hacen imposible la evidencia incompleta
contract.py   assert_legal_basis · assert_temporal_validity · assert_defensible
questions.py  Dossier — las diez preguntas del §49, ejecutables
errors.py     IncompleteEvidenceError, SyntheticLegalBasisError, …
```

Cinco tipos, **sólo uno es fundamento jurídico**:

| Tipo | ¿Fundamento? |
|---|---|
| `LEGAL_SOURCE` — norma recuperada | **sí, el único** |
| `MODEL_OUTPUT` — lo produjo un modelo | no |
| `DETERMINISTIC` — regla de código | no |
| `HUMAN` — persona validó | no por sí solo |
| `COMPARABLE` — CBP CROSS, EBTI, WCO | **nunca** |

Desde el PR #43, el tipo correcto **no basta**: `is_legal_basis` exige además
un origen real. `LEGAL_BASIS_ORIGINS` son los cinco menos `SYNTHETIC`, y una
norma sintética lanza `SyntheticLegalBasisError`. El motivo es que una norma
inventada cumple todos los campos que exige `LEGAL_SOURCE` —incluido un
`content_hash` perfectamente calculable— y aun así no es ley.

### `core/rgi_engine/` — RGI Engine ✅

Dos etapas: RGI 1→5 determinan la **partida**, RGI 6 desciende a **fracción**.
No toca la base ni llama a ningún modelo; toda consulta al catálogo lleva
`on_date` obligatorio.

RGI 2, 4 y 5 no están implementadas pero **no se saltan**: detectan sus
precondiciones y escalan a `HUMAN_REVIEW_REQUIRED`. `specificity` ya está
poblada, así que la RGI 3 a) desempata de verdad.

**Lección del 8 de septiembre.** Al cargar las 92 notas reales el motor dejó de
clasificar: daba una partida por excluida si la nota del capítulo contenía un
término de búsqueda, y la del Capítulo 84 menciona «portátiles» hablando de
herramientas de mano. Se quitó esa decisión de la capa determinista (PR #51).
Una exclusión falsa descarta la partida correcta con toda la apariencia de
rigor — es peor que no decidir.

### `core/product_dna/` · `core/classification/` ✅

Product DNA v0.1 con extracción multimodal. El saneamiento **sólo degrada**:
sin valor pasa a `MISSING`, sin localización baja a `INFERRED`, sin confianza
cae a `MISSING`. Nunca inventa un valor plausible.

El orquestador une DNA → RGI → Evidence y persiste la traza en `rgi_trace`.

### `core/shadow/` · `core/audit/` · `core/taxation/` · `core/opportunity/` ✅

Pedimento Espejo construye lo que *debería* declararse **sin mirar lo
declarado**, y sólo después compara. Money Finder es `Decimal` de punta a
punta. Lo no verificable se declara `unverifiable` y va a `shadow_reviews`: un
pedimento que nadie pudo verificar no está limpio, está sin verificar.

### `rag/` — RAG jurídico (§27) ✅ sin vectorizar

```
types.py      LegalChunk — vigencia y data_origin POR CHUNK
chunking.py   trocea por artículo y fracción; lee «(Reformado … DOF …)»
retrieval.py  recuperar() — filtro temporal y de procedencia
evidencia.py  a_legal_refs() → LegalRef, el puente al contrato
memoria.py    MemoriaChunkStore, sólo para desarrollo
ports.py      ChunkStore · Embedder
```

El almacén real es `database/repositories/chunks.py` sobre pgvector.
`POST /products/{id}/classify` ya fundamenta con el corpus.

Verificado contra la base compartida: para `2024-03-15` devuelve 8 artículos y
descarta los reformados el 2025-11-19; para `2026-09-01` devuelve los nuevos.
La regla 5 se cumple en producción, no sólo en tests.

**Los 274 chunks tienen `embedding` en NULL.** La columna es `vector(1536)`, el
índice HNSW está creado y `EMBEDDING_DIM = 1536` no se toca. Hoy la
recuperación es por término, no por similitud.

### `apps/api/` ✅ 17 endpoints · `apps/web/` ✅ 7 pantallas

⚠️ **El servicio systemd no recarga solo.** Entre el 8 y el 9 de septiembre
sirvió código anterior al PR #38 durante casi un día: 12 endpoints en vivo
contra 16 en `develop`, sin que nada lo delatara — `/health` respondía `ok`.
Tras mergear cualquier PR que toque `apps/api/`: `make service-restart`.

---

## 7. Qué falta

### Scorecard del §44

```
DATA           4 de 14   LIGIE ✅ (2 capítulos de 97) · NICO ✅ ·
                         Ley Aduanera ✅ · Anexo 22 ✅
                         RGCE ❌ · PROSEC ❌ · Regla 8a ❌ · NOM ❌ ·
                         Cuotas ❌ · CBP ❌ · EBTI ❌ · Banxico ❌ ·
                         ANAM/SAT/Data México ❌
CORE           4 de 4    Product DNA ✅ · RGI ✅ · Classification ✅ ·
                         Evidence ✅
SIMULATOR      0 de 8    synthetic/ tiene sólo __init__.py. El seed crea una
                         fila de cada cosa; eso no es un generador.
INTELLIGENCE   4 de 6    Shadow ✅ · Audit ✅ · Money ✅ · Opportunity ✅ ·
                         Sentinel ❌ · Knowledge Graph ❌
PRODUCT        1.5 de 3  Dashboard ✅ · Copilot ❌ · Demo AJR ⏳ guion escrito
```

### El vertical slice del §42 — cerrado

```
ficha técnica → Product DNA → RGI → Classification → Evidence →
pedimento sintético → Shadow → divergencia → Money Finder
      ✅            ✅        ✅            ✅         ✅
```

Está cerrado de punta a punta y **sin medir**. Es la distinción que importa:
593 tests en verde prueban el motor contra los casos que escribimos nosotros,
no contra verdad conocida.

### Lo que de verdad falta

| # | Hueco | Por qué importa |
|---|---|---|
| 1 | **Nadie ha medido el acierto** | El instrumento ya existe: `GET /metrics/classification` (PR #55). Lo que falta son los veredictos — 0 humanos, 7 casos en la bandeja sin tocar, 1 fila de Ground Truth. La métrica devuelve `null`, no `0`: la precisión es **desconocida**, no mala. |
| 2 | **274 chunks sin vectorizar** | `OPENAI_API_KEY` vacía. Sin vectores no hay búsqueda semántica, que es el punto del §27. |
| 3 | **Las 92 notas LIGIE no están en `legal_chunks`** | Viven en `legal_rules` y sólo las alcanza el motor determinista. Son justo las que separan 8471 de 8528. |
| 4 | **RGCE 2026** | La tercera pata del corpus, no iniciada. |
| 5 | **95 capítulos de tarifa** | Hoy 84 y 85. |

### Deuda técnica conocida

- `database/seeds/canonical_v0_1.py` escribe una evidencia `LEGAL_SOURCE` con
  `data_origin = SYNTHETIC`, saltándose `builder.legal_source()` por el orden
  del flush. El contrato la rechaza al leerla, pero un re-seed la recrea.
- `GroundTruthRecord` está diseñado para anomalías inyectadas (§26):
  `error_type`, `original_value`, `mutated_value`. **No sirve** para medir
  acierto de clasificación. Esa vía son las filas `HUMAN_VALIDATED` que
  comparten `product_dna_id` (ver §8, Persona 3).
- Los respaldos viven en el mismo disco que la base.

---

## 8. Backlog por persona

> Al 9 de septiembre: `develop` en `a47895f`, **0 PRs abiertos**, `main` en
> `v0.4`. Los tres documentos de encargo —`TAREA_P2_CORPUS_JURIDICO.md` y
> `TAREA_P3_RAG_INTEGRACION.md`— están cumplidos salvo lo que se lista abajo.

### Persona 2 — Brandon (Data Engineer)

| # | Tarea | Estado |
|---|---|---|
| 1 | **Verificar su push: `reform_note` + `rag/backfill_embeddings.py`** | 🔴 **bloquea a Persona 3.** Cree tener un PR abierto; no existe. La migración `dce813047e49` no está en el repo y `rag/` no tiene el backfill. |
| 2 | Notas LIGIE → `legal_chunks` | pendiente, no estaba en su encargo |
| 3 | RGCE 2026 | no iniciado, confirmar alcance |
| 4 | Ground Truth de anomalías (§26) | pendiente |
| 5 | Resto de la tarifa · Anexo 2.2.1 · las nueve fuentes | pendiente |

**Ya mergeado, no rehacer:** el `valid_from` por artículo (`valid_from_override`,
commit `421c592`) y el `notes_for()` acotado a `LegalDocument.kind == "TARIFF"`.
La base compartida da 180 de 274 artículos vigentes en 2024 gracias al primero.

### Persona 3 — Ulises (AI + Full Stack)

| # | Tarea | Estado |
|---|---|---|
| 1 | ~~Métrica de precisión~~ | ✅ PR #55, en vivo. Declara el cero: porcentajes en `null`, 0 revisadas de 7. |
| 2 | Vectorizar los 274 chunks | ⏸ espera llave |
| 3 | Revisar el backfill de Brandon | ⏸ espera su PR — **revisarlo, no rehacerlo** |
| 4 | Pantallas Regulatory Sentinel y Copilot | desbloqueadas: dependían del corpus |
| 5 | Knowledge Graph sobre Neo4j | sin dueño |

**Sobre la 1.** Una revisión humana **no sobrescribe** la decisión de la
máquina: crea una fila nueva `HUMAN_VALIDATED` que comparte `product_dna_id`
(`apps/api/routers/review.py`). De ese par salen *fraction accuracy* y *human
review rate*. Las dos vías se complementan: la de Brandon mide detección de
anomalías, ésta mide acierto de clasificación.

**Quién revisa.** No el equipo: un veredicto de quien construyó el sistema lo
mide contra sus propias suposiciones. Los revisores calificados son los de
AJR, y `docs/DEMO_AJR.md` cierra pidiéndoles diez pedimentos reales ya
cerrados. Ese es el mismo bloqueo, visto desde la demo.

### Persona 1 — Erick (Tech Lead)

| # | Tarea | Estado |
|---|---|---|
| 1 | ~~`make service-restart`~~ | ✅ hecho el 9-sep, 17 endpoints en vivo |
| 2 | **Llave de OpenAI** | 🔴 desatasca a P2 y P3 a la vez |
| 3 | Contestar a Ulises quién revisa | 🔴 es su único bloqueo real |
| 4 | Ratificar el uso de `HUMAN_VALIDATED` para medir acierto | toca el Canonical Model |
| 5 | Aplicar `dce813047e49` a la compartida | cuando exista |
| 6 | Sacar los respaldos de la laptop | 50 MB en el mismo disco que la base |
| 7 | Arreglar el seed (`LEGAL_SOURCE` + `SYNTHETIC`) | ver §7 |
| 8 | Decidir sobre RGI 3 c) y las reglas 2, 4 y 5 | pendiente |

---

## 9. La siguiente tarea

**Medir.** Es lo único que el proyecto no puede responder hoy, y lo pregunta
cualquiera en los primeros cinco minutos.

Tiene dos mitades y ninguna es código difícil:

1. **La métrica, aunque nazca vacía** — Persona 3, sin dependencias.
2. **Los veredictos que la llenen** — de AJR, no del equipo.

Todo lo demás del proyecto puede seguir avanzando en paralelo, pero el número
honesto de «cuánto llevamos» no se mueve hasta que alguien calificado revise
mercancía real. Hoy el motor está en ~85 **sin validar**: si el Ground Truth
revelara 60% de acierto, no valdría 85.

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
| `docs/DEMO_AJR.md` | guion de la demo, verificado contra el sistema |
| `docs/TAREA_P2_CORPUS_JURIDICO.md` | encargo del corpus a Persona 2 |
| `docs/TAREA_P3_RAG_INTEGRACION.md` | encargo del RAG a Persona 3 |
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
