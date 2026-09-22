# ADUANERO OS — Estado del proyecto y backlog

**Actualizado:** 2026-09-21  
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
apps/evaluacion/     harness y validadores    ✅ hs_accuracy · corpus_espejo
core/evidence/       Evidence Contract        ✅
core/rgi_engine/     RGI Engine               ✅
core/llm/            ModelProvider            ✅
core/prompts/        loader versionado        ✅
core/product_dna/    motor de extracción      ✅
core/classification/ orquestador              ✅ persiste las normas citadas
core/taxation/       Money Finder             ✅
core/audit/          Audit Engine             ✅
core/shadow/         Pedimento Espejo         ✅ contrasta el país de origen
core/opportunity/    Opportunity Finder       ✅
core/review/         revisión humana          ✅
rag/                 RAG jurídico (§27)       ✅ semántico, degrada a término
database/models/     29 entidades SQLAlchemy  ✅
database/migrations/ 14 migraciones aplicadas ✅
database/repositories/  chunks · notes · tariff · classification · review
database/seeds/      canonical_v0_1.py        ✅
schemas/             contratos Pydantic       ✅
ingestion/snice/     LIGIE · NICO · notas     ✅ los 97 capítulos
ingestion/dof/       Anexo 22                 ✅
ingestion/diputados/ Ley Aduanera             ✅
ingestion/{anam,banxico,cbp_cross,datamexico,ebti,sat,vucem,wco}/   ❌ VACÍOS
synthetic/           generador sintético      ❌ sólo __init__.py
graph/               Knowledge Graph          ⏳ aprobado 21-sep, en construcción
tests/               55 archivos, 781 tests   ✅
.github/workflows/ci.yml                      ✅ 6 jobs
```

### Base de datos — 29 tablas

Alembic en `9f5c85042bf1`. Conteos verificados el 21 de septiembre:

```
regulatory     legal_sources 4 · legal_documents 4 · legal_rules 366 ·
               legal_chunks 366 (vectorizados y enlazados a su norma) ·
               tariff_fractions 8,136 · nicos 11,503 · customs_offices 127 ·
               units_of_measure 22 · pedimento_claves 66 ·
               non_tariff_regulations 37 · regulatory_events 0
operational    pedimentos 1 · pedimento_items 1 · el resto, 1 fila
               del seed. ESTE ES EL CUELLO DE BOTELLA: el corpus de 15
               pedimentos y 180 partidas está validado y sin cargar.
intelligence   classification_decisions 9 · candidates 142 ·
               evidence_records 93 · shadow_reviews 2 ·
               risk_findings 1 · ground_truth_records 1 ·
               veredictos humanos 0
raw            sin tablas: el crudo vive en MinIO
```

Las 366 normas son `OFFICIAL`: 274 artículos de la Ley Aduanera (220 con
`reform_note`) y 92 notas de Sección y Capítulo de la LIGIE. **La tarifa está
completa**: 8,136 fracciones de los 97 capítulos.

### RAW en MinIO — siete documentos con su hash

```
diputados/ley_aduanera_20251119.pdf
dof/anexo22_20260115.pdf
snice/fracciones_20260420.xlsx
snice/ligie_unificada_20250728.pdf
snice/nico_20240415.xlsx
sintetico/corpus_espejo_v1_20260921.pdf      ← corpus de laboratorio
sintetico/corpus_espejo_v1_20260921.json
```

La regla 7 se cumple de punta a punta: nada de lo anterior se parseó sin que
el crudo estuviera antes en MinIO con su `content_hash`.

El prefijo `sintetico/` no es decorativo. Los otros tres dicen de qué sistema
salió el archivo; el corpus no sale de ninguno, es de laboratorio. Quien abra
el bucket dentro de seis meses tiene que distinguir a simple vista un
documento oficial de uno que no lo es.

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

**Lección del 21 de septiembre.** Clasificando las descripciones de un
pedimento real, el motor resolvió 4 de 9 y **ninguna** coincidió: unos cables
eléctricos acabaron en 9806 —operaciones especiales— y «COMPUTADORAS
PORTATILES» no encontró ni una candidata. La causa, medida contra la base:
«portatiles» daba 0 fracciones y «portátiles» 11; «algodon» 0 y «algodón» 74.
Un pedimento se escribe en mayúsculas y sin acentos; la tarifa los lleva. El
prefiltro era un `ILIKE` sensible a acentos (#82). Ninguno de los 741 tests lo
veía, porque las fixtures están escritas con acentos y con el vocabulario de
la tarifa. Quedan dos causas vivas: el 26% de las fracciones sólo dice «Los
demás» y el texto de la partida de 4 dígitos no está cargado en ninguna
columna.

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

**El 21 de septiembre aprendió a comprobar tres cosas más**, y las tres salen
del propio documento, sin fuente externa (#85 y #90):

- **el país de origen** contra el del proveedor, al que se llega por la
  cadena partida → factura → proveedor. Sale como revisión humana y no como
  error: un pedimento con orígenes mixtos es legítimo, y tratarlo como error
  duro llenaría de ruido el día que entren pedimentos reales;
- **el NICO contra el catálogo**: que el declarado exista dentro de la
  fracción declarada. Es lo único que el catálogo puede afirmar solo. Que sea
  el NICO *correcto* para esa mercancía exige ficha técnica, y eso se reporta
  como hueco con su nombre, no como acierto;
- **el valor en aduana contra la propia partida**: precio pagado más
  incrementables (art. 65 de la Ley Aduanera). Antes el esperado copiaba al
  declarado y la comparación no podía dispararse nunca.

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
                         RGCE ⏳ parser escrito, sin PR desde el 14-sep
                         PROSEC ❌ · Regla 8a ❌ · NOM ❌ · Cuotas ❌ ·
                         CBP ❌ · EBTI ❌ · Banxico ❌ · ANAM/SAT/Data México ❌
CORE           4 de 4    Product DNA ✅ · RGI ✅ · Classification ✅ ·
                         Evidence ✅
SIMULATOR      0 de 8    ⏳ DESBLOQUEADO el 21-sep: hay corpus externo de 15
                         pedimentos y 180 partidas, validado y sin cargar
INTELLIGENCE   5 de 6    Shadow ✅ · Audit ✅ · Money ✅ · Opportunity ✅ ·
                         Sentinel ✅ · Knowledge Graph ⏳ aprobado el 21-sep,
                         en construcción como proyección de Postgres
PRODUCT        2.5 de 3  Dashboard ✅ · Copilot ✅ · Demo AJR ⏳ sin fecha;
                         guion re-verificado contra el sistema el 21-sep
```

### El vertical slice del §42 — cerrado y sin medir

```
ficha técnica → Product DNA → RGI → Classification → Evidence →
pedimento sintético → Shadow → divergencia → Money Finder
      ✅            ✅        ✅            ✅         ✅
```

Está cerrado de punta a punta y **sin medir**. 768 tests en verde prueban el
motor contra los casos que escribimos nosotros, no contra verdad conocida.

Van **tres** fallos graves que pasaban todos sus tests y sólo aparecieron
ejecutando contra datos reales: la RGI 3 c) que resolvía sin pedir revisión, el
reordenamiento que destruía el orden semántico, y el prefiltro sensible a
acentos que no encontraba ninguna candidata para una descripción escrita como
se escriben los pedimentos. Los tres son del mismo tipo: verde en el repo,
equivocado en producción.

### Lo que de verdad falta

| # | Hueco | Por qué importa |
|---|---|---|
| 1 | **El corpus sin cargar** | 15 pedimentos, 180 partidas, 60 anomalías sembradas, validado el 21-sep sin un solo defecto en ocho comprobaciones. Mientras no se cargue, la capa operativa sigue con 1 partida y no hay nada que medir. **Es el camino crítico.** |
| 2 | **Nadie ha medido el acierto** | 0 veredictos humanos, 1 fila de Ground Truth. Ya no es por falta de datos: es por falta de carga. Con el corpus dentro salen precision, recall y F1 sobre 54 eventos medibles y 126 partidas limpias. |
| 3 | **RGCE 2026** | El parser lleva desde el 14-sep en la máquina de Persona 2 sin PR. El Sentinel ya distingue una resolución anual de una reforma, así que no hay nada bloqueándolo. |
| 4 | **El texto de partida y subpartida de la LIGIE** | El 26% de las 8 136 fracciones sólo dice «Los demás», y el texto de los niveles de 4 y 6 dígitos no está en ninguna columna. La RGI 1 clasifica por el texto de las partidas y no lo tenemos: es la causa de fondo de que el motor no encuentre candidatas. |
| 5 | **Knowledge Graph** | Aprobado el 21-sep y en construcción. Es **proyección de Postgres, nunca fuente**: se reconstruye con MERGE por el id de la fila, y nada que fundamente jurídicamente puede citarse desde ahí. Es lo único que falta de INTELLIGENCE. |
| 6 | **Las fuentes vacías** | `anam`, `banxico`, `cbp_cross`, `datamexico`, `ebti`, `sat`, `vucem`, `wco` y el Anexo 2.2.1 (fracción → NOM). Sin este último el Pedimento Espejo declara la NOM como no verificable en cada partida. |

### Deuda técnica conocida

- **Seis anomalías del corpus son indetectables por construcción.** Las de
  `CANTIDAD_UMC_INCONSISTENTE`: el precio unitario del PDF se calculó con la
  cantidad ya alterada, así que no hay inconsistencia aritmética, y los kg por
  unidad caen dentro de la dispersión de sus propias partidas limpias. Se
  cargan con `expected_detection = false` y quedan fuera del recall. El techo
  honesto es 54 de 60.
- **`invoice_items.country_of_origin` es una trampa.** El corpus no trae
  facturas; llenarla con el país esperado metería la respuesta en las tablas
  operativas. Se deja en NULL: la expectativa sale de `supplier.country`, que
  sí está impreso en el documento.
- **La RGI 3 c) sigue desempatando por orden de numeración** entre candidatas
  con la misma `specificity`, lo que favorece los capítulos altos. Sale
  marcado para revisión humana desde el #69, pero el código que enseña sigue
  siendo el equivocado.
- **Una fila del seed con `document_refs` vacío** en la compartida. El código
  está arreglado (#67); la fila vieja sigue porque la escritura directa a la
  base quedó bloqueada por permisos.
- `GroundTruthRecord` está diseñado para anomalías inyectadas (§26) y **no
  sirve** para medir acierto de clasificación; esa vía son las filas
  `HUMAN_VALIDATED` que comparten `product_dna_id`.
- **Respaldos: 97 MB en el mismo disco que la base, y no hay a dónde
  moverlos hoy.** Esta máquina tiene un solo disco. Sacarlos exige otra
  máquina, y las dos de la tailnet pertenecen a otros usuarios: `yayo` no
  tiene SSH escuchando y Taildrop no cruza entre dueños distintos. Queda
  esperando una acción del dueño de `yayo`: levantar `sshd`. El script ya
  acepta destino por `ADUANERO_BACKUP_DIR`.
- **La llave de OpenAI** viajó por un chat el 9-sep y sigue sin rotarse.
  Instrucciones entregadas el 21-sep; la rotación es de Persona 1 y la llave
  nueva no vuelve a pasar por un chat.

**Cerrado desde el 14-sep:** el doble veredicto (#79), el tope de olas del
Sentinel (#78), el emparejamiento de la métrica por DNA y tiempo (#81) y la
rama suelta de `legal-chunks-legal-rule-id`.

---

## 8. Backlog por persona

> Al 21 de septiembre, cierre del día. **Nueve PRs mergeados** (#82 a #90),
> 0 abiertos, `develop` en `8ecbd04`. Decisiones de Persona 1 del 21-sep: el
> Knowledge Graph se hace, el enum de errores se amplía, y **la demo es el
> miércoles 23**.

### Persona 2 — Brandon (Data Engineer)

| # | Tarea | Estado |
|---|---|---|
| 1 | **El cargador del corpus** | 🔴 camino crítico. RAW a MinIO con hash, 180 partidas a operacional con sólo lo OBSERVADO, 60 eventos a `ground_truth_records`. Nada lo bloquea: la migración del enum está aplicada |
| 2 | **La cadena del proveedor** | 🔴 parte del mismo cargador. Sin `suppliers`, `invoices` e `invoice_item_id` ligado, la comprobación de país no corre sobre ninguno de los 15 pedimentos |
| 3 | **Abrir el PR del parser de RGCE** | 🔴 lleva desde el 14-sep sin PR |
| 4 | Texto de partida y subpartida de la LIGIE | después de la carga |
| 5 | Reconocimiento de CBP CROSS · Anexo 2.2.1 | después |

### Persona 3 — Ulises (AI + Full Stack)

| # | Tarea | Estado |
|---|---|---|
| 1 | **Métrica de detección (§26)** | ⏸ espera la carga. TP, FP, FN, TN, precision, recall y F1, con los tres límites declarados |
| 2 | **Knowledge Graph** | 🟢 diseño aprobado el 21-sep, en construcción. Proyección de Postgres, `data_origin` en los nodos, nombres del §28, y las omisiones (NOM, PROSEC, Treaty, RegulatoryEvent, Manufacturer) escritas en el código con la fuente que desbloquea cada una |
| 3 | Harness de `hs_accuracy` contra CBP CROSS | ⏸ baja prioridad: el corpus mide sin depender de nadie |

**Ya hecho:** Sentinel con `total_olas` (#78), doble veredicto (#79), harness
de sólo lectura (#80), `reviews_decision_id` (#81), país de origen (#85).

### Persona 1 — Erick (Tech Lead)

| # | Tarea | Estado |
|---|---|---|
| 1 | **Verificar la carga de Brandon** antes de dar luz verde a la métrica | cuando llegue |
| 2 | Rotar la llave de OpenAI | 🔴 doce días abierta |
| 3 | Respaldos fuera de esta máquina | ⏸ espera que Edi levante SSH en `yayo` |
| 4 | Análisis de ANA frente a ADUANERO OS | define el discurso de la demo |

**Cerrado el 21-sep:** enum ampliado y aplicado (#83), validador de corpus
(#84), guion de la demo re-verificado (#86), columnas de precio pagado e
incrementables (#89), corpus subido a MinIO con su hash, Knowledge Graph
decidido, fecha de demo fijada.

---

## 9. La siguiente tarea

**Cargar el corpus.** Todo lo demás está listo a su alrededor: el enum acepta
los diez tipos, el validador confirma que el corpus no tiene defectos, la
comprobación de país existe y la métrica está diseñada. Falta meter 180
partidas a la base.

El día que esté cargado, el proyecto podrá decir por primera vez una frase que
hoy no puede: *«el Pedimento Espejo detecta el X% de las anomalías con un Y%
de falsos positivos, medido sobre 180 partidas»*. Sin AJR, sin CBP CROSS y sin
gastar un peso en modelo.

La segunda, en paralelo y sin dependencias: el Knowledge Graph, que ya está
aprobado y es lo único que le falta a INTELLIGENCE.

**Y todo esto con una fecha: la demo es el miércoles 23.** El guion ya está
verificado contra el sistema, así que la demo existe con o sin corpus. Lo que
el corpus cambia no es si se puede dar, es qué se enseña: un tablero con 180
partidas en vez de una, y una cifra medida donde hoy la respuesta honesta es
«no lo hemos medido». El martes a las 14:00 se decide con cuál de las dos se
entra, y a las 17:00 se congela: nada que toque core, apps o datos se mergea
después de esa hora.

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
| `docs/DEMO_AJR.md` | guion de la demo, verificado contra el sistema el 21-sep |
| `docs/AJR_Y_ANA.md` | quién es AJR y qué es ANA |
| `docs/PETICION_AJR.md` | ⏸ en pausa — petición de diez pedimentos a AJR |
| `apps/evaluacion/corpus_espejo.py` | valida un corpus antes de cargarlo |
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
