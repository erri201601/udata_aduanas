# ADUANERO OS — Estado del proyecto y backlog

**Actualizado:** 2026-09-14  
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
jurídicas reales y datos operativos sintéticos. Quién es AJR y qué es ANA:
`docs/AJR_Y_ANA.md`.

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
| MinIO | `:9000` (API) · `:9001` (consola) | `aduanero-raw` con 5 documentos; `aduanero-docs` vacío |

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
apps/api/            FastAPI, 21 endpoints    ✅ 12 routers
apps/web/            React + TS + Vite        ✅ 10 de 10 del §32
core/evidence/       Evidence Contract        ✅
core/rgi_engine/     RGI Engine               ✅
core/llm/            ModelProvider            ✅
core/prompts/        loader versionado        ✅
core/product_dna/    motor de extracción      ✅
core/classification/ orquestador              ✅ persiste las normas citadas
core/taxation/       Money Finder             ✅
core/audit/          Audit Engine             ✅
core/shadow/         Pedimento Espejo         ✅
core/opportunity/    Opportunity Finder       ✅
core/review/         revisión humana          ✅
rag/                 RAG jurídico (§27)       ✅ semántico, degrada a término
database/models/     29 entidades SQLAlchemy  ✅
database/migrations/ 11 migraciones aplicadas ✅
database/repositories/  chunks · notes · tariff · classification · review
database/seeds/      canonical_v0_1.py        ✅
schemas/             contratos Pydantic       ✅
ingestion/snice/     LIGIE · NICO · notas     ✅ los 97 capítulos
ingestion/dof/       Anexo 22                 ✅
ingestion/diputados/ Ley Aduanera             ✅
ingestion/{anam,banxico,cbp_cross,datamexico,ebti,sat,vucem,wco}/   ❌ VACÍOS
synthetic/           generador sintético      ⏸ en pausa · sólo __init__.py
graph/               Knowledge Graph          ❌ sólo __init__.py · Neo4j con 0 nodos
tests/               49 archivos, 691 tests   ✅
.github/workflows/ci.yml                      ✅ 6 jobs
```

### Base de datos — 29 tablas

Alembic en `5443e24b5a3f`. Conteos verificados el 14 de septiembre:

```
regulatory     legal_sources 4 · legal_documents 4 · legal_rules 366 ·
               legal_chunks 366 (366 vectorizados · 366 enlazados a su norma) ·
               tariff_fractions 8,136 · nicos 11,503 · customs_offices 127 ·
               units_of_measure 22 · pedimento_claves 66 ·
               non_tariff_regulations 37 · regulatory_events 0
operational    clients · suppliers · products · invoices · invoice_items ·
               coves · pedimentos · pedimento_items · synthetic_scenarios
               — 1 fila cada una, del seed
intelligence   classification_decisions 9 · classification_candidates 142 ·
               evidence_records 93 · product_dnas 1 · product_attributes 4 ·
               shadow_reviews 2 · risk_findings 1 · opportunity_findings 0 ·
               ground_truth_records 1
raw            sin tablas: el crudo vive en MinIO
```

Las 366 normas son `OFFICIAL`: 274 artículos de la Ley Aduanera (220 con
`reform_note`) y 92 notas de Sección y Capítulo de la LIGIE. **La tarifa está
completa**: 8,136 fracciones de los 97 capítulos, 8,094 con tasa IGI.

### RAW en MinIO — cinco documentos con su hash

```
diputados/ley_aduanera_20251119.pdf
dof/anexo22_20260115.pdf
snice/fracciones_20260420.xlsx
snice/ligie_unificada_20250728.pdf
snice/nico_20240415.xlsx
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

**Lección del 9 de septiembre.** La RGI 3 c) —«la última por orden de
numeración»— resolvía un empate entre 8471 y 8528 eligiendo el monitor, lo
marcaba `RESOLVED` y **no pedía revisión**, aunque su propio razonamiento decía
que hacía falta. Todos los tests pasaban. Desde el #69 la regla sigue
resolviendo —el código es el que prescribe— pero declara
`requires_human_review` y la traza lo respeta. Una resolución limpia sigue sin
pedir revisión.

### `core/product_dna/` · `core/classification/` ✅

Product DNA v0.1 con extracción multimodal. El saneamiento **sólo degrada**:
sin valor pasa a `MISSING`, sin localización baja a `INFERRED`, sin confianza
cae a `MISSING`. Nunca inventa un valor plausible.

El orquestador une DNA → RGI → Evidence, persiste la traza en `rgi_trace` y,
desde el #73, las normas que citó en `legal_rule_ids`.

### `core/shadow/` · `core/audit/` · `core/taxation/` · `core/opportunity/` ✅

Pedimento Espejo construye lo que *debería* declararse **sin mirar lo
declarado**, y sólo después compara. Money Finder es `Decimal` de punta a
punta. Lo no verificable se declara `unverifiable` y va a `shadow_reviews`: un
pedimento que nadie pudo verificar no está limpio, está sin verificar.

### `rag/` — RAG jurídico (§27) ✅ semántico

```
types.py      LegalChunk — vigencia, data_origin y legal_rule_id POR CHUNK
chunking.py   trocea por artículo y fracción; lee «(Reformado … DOF …)»
retrieval.py  recuperar() — filtro temporal y de procedencia
evidencia.py  a_legal_refs() → LegalRef, el puente al contrato
embedder.py   EmbedderDegradable — convierte la pregunta en vector
memoria.py    MemoriaChunkStore, sólo para desarrollo
ports.py      ChunkStore · Embedder
```

El almacén real es `database/repositories/chunks.py` sobre pgvector, y la regla
5 se cumple en producción: para `2024-03-15` descarta los artículos reformados
el 2025-11-19.

**La búsqueda es semántica y degrada, no tumba** (PR #68). Los 366 chunks
tienen vector (`text-embedding-3-small`, 1536) y `classify` y el Copilot los
consumen. Si el proveedor falla —429, timeout, sin llave— la petición no cae:
sigue por término y vigencia, y lo declara en `modo_busqueda`. Verificado con
un 429 simulado contra la base real.

**Las citas son auditables** (PRs #70 y #73). Cada chunk apunta a su fila de
`legal_rules` por la terna (documento, artículo, `valid_from`), y cada
clasificación guarda en `legal_rule_ids` qué normas citó. Con eso el Sentinel
dejó de ser `trazable: false`: hoy 1 de las 9 decisiones tiene citas — las 8
anteriores al #73 no las guardaban.

### `apps/api/` ✅ 21 endpoints · `apps/web/` ✅ 10 de 10 pantallas

La bandeja de revisión dice por qué está cada caso (PR #74), incluido el que la
RGI 3 c) resolvió sin razón sustantiva. `GET /metrics/classification` declara
la precisión como `null` mientras nadie revise, no como `0`.

⚠️ **El servicio systemd no recarga solo.** Entre el 8 y el 9 de septiembre
sirvió código anterior al PR #38 durante casi un día sin que nada lo delatara.
Tras mergear cualquier PR que toque `apps/api/` o los modelos:
`make service-restart`.

---

## 7. Qué falta

### Qué desbloquea cada llave

No son intercambiables, y confundirlas cuesta una tarde. Verificado el 9 de
septiembre con una llamada real:

| | Anthropic ✅ | OpenAI ✅ | Gemini ❌ |
|---|---|---|---|
| `generate` · `generate_structured` · `analyze_image` | **sí** | sí | sí |
| `embed` | **no existe** | `text-embedding-3-small`, 1536 | `text-embedding-004` |

**Lo que la llave de Anthropic desbloquea** es el Product DNA leyendo fichas
técnicas e imágenes de verdad (§16). Hasta ahora toda la telemetría de modelo
en la base venía del seed, marcada `SYNTHETIC`.

**Lo que no desbloquea es el §27.** Anthropic no publica endpoint de
embeddings: `AnthropicProvider.default_embedding_model` es `None` a propósito y
`embed()` lanza `ProviderCapabilityError` en vez de devolver un vector
inventado. Por eso hizo falta la de OpenAI, específicamente.

`text-embedding-3-small` devuelve 1536, que es exactamente la columna: cero
migración. Gemini declara `text-embedding-004`, cuya dimensionalidad por defecto
**no es 1536** — usarlo obligaría a migrar y reconstruir el índice HNSW.

⚠️ **La llave de OpenAI viajó por un chat.** Debe rotarse; la de reemplazo va
directa al `.env` del dev server.

### Scorecard del §44

```
DATA           4 de 14   LIGIE ✅ (los 97 capítulos) · NICO ✅ ·
                         Ley Aduanera ✅ · Anexo 22 ✅
                         RGCE ⏳ reconocimiento hecho, carga pendiente
                         PROSEC ❌ · Regla 8a ❌ · NOM ❌ · Cuotas ❌ ·
                         CBP ❌ · EBTI ❌ · Banxico ❌ · ANAM/SAT/Data México ❌
CORE           4 de 4    Product DNA ✅ · RGI ✅ · Classification ✅ ·
                         Evidence ✅
SIMULATOR      0 de 8    ⏸ EN PAUSA por decisión de Persona 1 (14-sep):
                         se omiten los pedimentos, reales y sintéticos
INTELLIGENCE   5 de 6    Shadow ✅ · Audit ✅ · Money ✅ · Opportunity ✅ ·
                         Sentinel ✅ trazable · Knowledge Graph ❌ (0 nodos)
PRODUCT        2.5 de 3  Dashboard ✅ · Copilot ✅ · Demo AJR ⏳ sin fecha;
                         secciones 3 y 4 del guion por re-verificar
```

### El vertical slice del §42 — cerrado y sin medir

```
ficha técnica → Product DNA → RGI → Classification → Evidence →
pedimento sintético → Shadow → divergencia → Money Finder
      ✅            ✅        ✅            ✅         ✅
```

Está cerrado de punta a punta y **sin medir**. 691 tests en verde prueban el
motor contra los casos que escribimos nosotros, no contra verdad conocida. Los
dos fallos graves del 9 de septiembre —la RGI 3 c) y el reordenamiento que
destruía el orden semántico— pasaban todos sus tests y sólo aparecieron
ejecutando contra datos reales.

### Lo que de verdad falta

| # | Hueco | Por qué importa |
|---|---|---|
| 1 | **Nadie ha medido el acierto** | `fraction_accuracy` es `null`: 0 veredictos, 1 fila de Ground Truth. Con los pedimentos en pausa, la única medición que no depende de nosotros es `hs_accuracy` a 6 dígitos contra fallos de **CBP CROSS**: la descripción la escribió un tercero y la clasificación la decidió una aduana. |
| 2 | **RGCE 2026** | Reconocimiento hecho (`docs/RECONOCIMIENTO_RGCE_2026.md`): ~550 reglas, parser nuevo, vigencias de excepción en los Transitorios Tercero y Cuarto. Faltan el parser y la carga. |
| 3 | **Knowledge Graph** | Neo4j encendido desde el principio con 0 nodos. Es lo único que falta de INTELLIGENCE, y sigue sin decisión. |
| 4 | **Las fuentes vacías** | `anam`, `banxico`, `cbp_cross`, `datamexico`, `ebti`, `sat`, `vucem`, `wco` y el Anexo 2.2.1 (fracción → NOM). Sin este último el Pedimento Espejo declara la NOM como no verificable en cada partida. |

### Deuda técnica conocida

- **Doble veredicto.** `POST /review/{id}` sólo rechaza revisar una fila que ya
  es `HUMAN_VALIDATED`; sobre una decisión de máquina ya revisada crea un
  segundo veredicto, y `human_review_rate` puede pasar del 100 %.
- **Tope de olas del Sentinel.** `TOPE_REFORMAS = 12` sin total. Con RGCE 2026
  —una resolución anual que entra entera el mismo día— las olas viejas se
  caerían sin aviso y un reemplazo anual se leería como reforma.
- **Una fila del seed con `document_refs` vacío** en la compartida. El código
  está arreglado (#67); la fila vieja sigue porque la escritura directa a la
  base quedó bloqueada por permisos.
- `GroundTruthRecord` está diseñado para anomalías inyectadas (§26) y **no
  sirve** para medir acierto de clasificación; esa vía son las filas
  `HUMAN_VALIDATED` que comparten `product_dna_id`.
- **Respaldos:** 68 MB en el mismo disco que la base.
- **Rama suelta** `feat/legal-chunks-legal-rule-id`: su commit ya está en
  `develop`; se puede borrar.

---

## 8. Backlog por persona

> Al 14 de septiembre. **Sin actividad del 9 al 14**: cero commits de código y
> la última escritura en la base es del 9-sep a las 17:07. Decisión de Persona
> 1 del 14-sep: **se omiten los pedimentos por ahora**, reales y sintéticos.

### Persona 2 — Brandon (Data Engineer)

| # | Tarea | Estado |
|---|---|---|
| 1 | **RGCE 2026** — parser con tests, luego carga | 🟢 recomendado: corte en 3 piezas, sólo el cuerpo de reglas, y las 13 reglas del Transitorio Cuarto fuera hasta tener fuente de su vigencia |
| 2 | Anexo 6 de las RGCE, PR aparte | después del cuerpo. Un criterio de clasificación, derogado |
| 3 | **Reconocimiento de CBP CROSS** | 🟢 términos de uso, formato y rulings bajo el SA 2022. Sin cargar nada |
| 4 | Generador sintético (§24) | ⏸ en pausa |
| 5 | Banxico · Anexo 2.2.1 · resto de fuentes | después |

**Ya hecho, no se rehace:** tarifa completa, `legal_chunks.legal_rule_id` por
la terna (#70), backfill con commit por lote (#64), `reform_note` (#58).

### Persona 3 — Ulises (AI + Full Stack)

| # | Tarea | Estado |
|---|---|---|
| 1 | **Sentinel antes de RGCE**: `total_olas`, agrupar por documento, no leer un reemplazo anual como reforma | 🔴 tiene que entrar antes de la carga de Brandon |
| 2 | **Doble veredicto** en `POST /review/{id}` | 🟢 si necesita columna nueva, la aprueba Persona 1 |
| 3 | **Harness de `hs_accuracy`** contra CBP CROSS | ⏸ espera el formato de Brandon. No persiste y no filtra la respuesta al motor |
| 4 | Knowledge Graph | ⏸ espera decisión |

**Ya hecho:** embeddings con degradación (#68), citas persistidas y Sentinel
trazable (#73), bandeja con causas (#74), camino de entrada de AJR (#75, que
queda como está).

### Persona 1 — Erick (Tech Lead)

| # | Tarea | Estado |
|---|---|---|
| 1 | Confirmar a Brandon el alcance de RGCE | recomendación escrita en su prompt |
| 2 | `data_origin` de CBP CROSS | recomendado `PUBLIC` |
| 3 | Rotar la llave de OpenAI | pendiente |
| 4 | Destino de los respaldos | `carlos` o `yayo` |
| 5 | Knowledge Graph: sí o no | pendiente |
| 6 | Análisis de ANA frente a ADUANERO OS | define el discurso de la demo |
| 7 | Fecha de la demo | sin fecha |

**Cerrado desde el día 9:** RGI 3 c) decidida y arreglada (#69), llave de
OpenAI puesta, `dce813047e49` y `5443e24b5a3f` aplicadas, AJR y ANA
documentados (`docs/AJR_Y_ANA.md`).

---

## 9. La siguiente tarea

**El ajuste del Sentinel, antes que nada** — Persona 3. No por ser lo más
grande, sino porque es lo único con orden forzoso: si la carga de RGCE 2026
entra primero, el Sentinel empieza a presentar ~535 normas de una resolución
anual como una ola de reforma.

Después, **medir sin depender de nadie**: el reconocimiento de CBP CROSS
(Persona 2) y el harness de `hs_accuracy` encima (Persona 3). Es la única cifra
de acierto disponible con los pedimentos en pausa, y tiene que presentarse con
su límite: mide los 6 dígitos del Sistema Armonizado, no la fracción mexicana.

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
| `docs/DEMO_AJR.md` | guion de la demo; secciones 3 y 4 por re-verificar |
| `docs/AJR_Y_ANA.md` | quién es AJR y qué es ANA |
| `docs/PETICION_AJR.md` | ⏸ en pausa — petición de diez pedimentos a AJR |
| `docs/RECONOCIMIENTO_RGCE_2026.md` | reconocimiento de RGCE 2026, antes de cargar |
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
