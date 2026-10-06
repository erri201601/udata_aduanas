# ADUANERO OS — Estado del proyecto y backlog

**Actualizado:** 2026-10-06  
**Mantiene:** Persona 1 (Erick)

Las cifras de este documento se verificaron contra la base y el repositorio el
6 de octubre. Las que dependen de otra persona van marcadas: este documento no
afirma el avance de nadie que no haya empujado código.

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
un documento interno, fuera del repositorio.

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
| API (FastAPI) | `<IP-DEL-DEV-SERVER>:8080` | servicio systemd `aduanero-api` |
| PostgreSQL 16 + pgvector | `<IP-DEL-DEV-SERVER>:5433` | **no 5432** |
| Neo4j | `:7474` (browser) · `:7687` (bolt) | vacío, sin usar |
| Redis | `:6379` | sin usar |
| MinIO | `:9000` (API) · `:9001` (consola) | `aduanero-raw` con 13 archivos (80 MB); `aduanero-docs` vacío |

⚠️ **En el puerto 5432 hay un PostgreSQL nativo de OTRO proyecto**
(`Conta_inteligente/Tzol_Udata`). No se toca ni para leer.

Cada puerto se publica dos veces: en `127.0.0.1` y en `${TEAM_BIND_ADDR}` (la
IP de Tailscale). Nunca en `0.0.0.0`.

### Tailnet

Tres nodos: el dev server, la máquina de Persona 3 y la de respaldos. Las IP
no van aquí: el repositorio es público desde el 28-sep y una dirección del
tailnet con su nombre de host es un mapa, no una configuración. Las entrega
Persona 1 por canal seguro.

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
verificación de restauración en cada corrida. **369 MB, 21 volcados, y siguen
en el mismo disco que la base.** La réplica a `yayo` está configurada y falla
por la razón más simple: la máquina está apagada (`Connection timed out`). El
script sale con código 3 en vez de dar un verde falso.

La consola web escucha **sólo en `127.0.0.1`**, así que hoy sólo se puede usar
sentado en el dev server. Abrirla en el tailnet es decisión de Persona 1 y no
está tomada.

---

## 3. Estructura del código

```
apps/api/            FastAPI, 23 endpoints    ✅ 12 routers
apps/web/            React + TS + Vite        ✅ 11 pantallas (10 del §32 + Revisión)
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
ingestion/dof/       Anexo 22 · RGCE 2026     ✅
ingestion/se/        Anexo 2.4.1 (NOM)        ✅ 456 correlaciones
ingestion/diputados/ Ley Aduanera             ✅
ingestion/{anam,banxico,cbp_cross,datamexico,ebti,sat,vucem,wco}/   ❌ VACÍOS
ingestion/sintetico/ corpus de laboratorio    ✅ cargador y validador
synthetic/           generador sintético      ❌ sólo __init__.py (sin uso)
graph/               Knowledge Graph          ⏳ aprobado 21-sep, sin cerrar
tests/               1 161 tests              ✅
.github/workflows/ci.yml                      ✅ 6 jobs
```

### Base de datos — 34 tablas

Alembic en `e118b7bea934`. Conteos verificados el 6 de octubre:

```
regulatory     legal_sources 4 · legal_documents 5 · legal_rules 905 ·
               legal_chunks 2,144 · tariff_fractions 8,136 ·
               tariff_headings 6,855 (ADR 0002) · tariff_heading_groups ·
               nicos 11,503 · fraction_nom_requirements 456 (Anexo 2.4.1) ·
               customs_offices 127 · units_of_measure 22 ·
               pedimento_claves 66 · pedimento_identifiers 174 ·
               non_tariff_regulations 37 · nomenclature_synonyms 13 firmados ·
               regulatory_events 0
operational    pedimentos 16 · pedimento_items 181 · products 181
               EL CORPUS ESTÁ CARGADO. Era el cuello de botella del 21-sep.
intelligence   classification_decisions 5,209 · candidates 32,370 ·
               evidence_records 26,559 · shadow_reviews 390 ·
               risk_findings 2,126 · opportunity_findings 119 ·
               ground_truth_records 61 ·
               veredictos humanos 59 (36 con NICO, 3 de «falta información»)
raw            sin tablas: el crudo vive en MinIO
```

El volumen de `classification_decisions` es alto porque cada medición
reclasifica los 181 productos y **conserva** la decisión anterior: la bandeja y
la métrica leen la última por ficha (`product_dna_id`), no la unión de todas.

Las 905 normas son `OFFICIAL`. **La tarifa está completa**: 8,136 fracciones de
los 97 capítulos, y desde el ADR 0002 cada nivel —partida, subpartida y grupo
de guion— tiene su propio texto en `tariff_headings`, que es lo que faltaba
para que el motor supiera de qué habla una fracción que sólo dice «Los demás».

### RAW en MinIO — 13 objetos, listados el 6 de octubre

```
diputados/ley_aduanera_20251119.pdf             2.0 MB
diputados/ligie_2022_texto_vigente.pdf         18.3 MB
dof/anexo22_20260115.pdf                        9.3 MB
dof/rgce_2026.html                              4.8 MB   ← RGCE 2026
snice/anexo_2_4_1_noms_20220516.pdf             6.8 MB   ← fracción → NOM
snice/fracciones_20260420.xlsx                  0.7 MB
snice/ligie_unificada_20250728.pdf             32.9 MB
snice/nico_20240415.xlsx                        0.8 MB
sintetico/corpus_espejo_v1_20260921.pdf         0.1 MB   ← corpus de laboratorio
sintetico/corpus_espejo_v1_20260921.json        0.5 MB
product-dna/<product_id>/<content_hash>         3 fichas subidas por la API
```

`aduanero-docs` sigue vacío.

⚠️ Uno de los tres objetos de `product-dna/` pesa **0 KB**. Una ficha subida
vacía con su hash calculado es una evidencia que parece completa y no lo es:
conviene mirarlo antes de que una decisión se apoye en ella.

La regla 7 se cumple de punta a punta: nada de lo anterior se parseó sin que
el crudo estuviera antes en MinIO con su `content_hash`.

El prefijo `sintetico/` no es decorativo. Los otros dicen de qué sistema salió
el archivo; el corpus no sale de ninguno, es de laboratorio. Quien abra el
bucket dentro de seis meses tiene que distinguir a simple vista un documento
oficial de uno que no lo es.

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

**Lo que cambió entre el 4 y el 5 de octubre.** Veinticinco PRs (#169 a #193)
sobre el motor, la bandeja y la medición, a partir de dos dictámenes de un
clasificador real. El motor pasó de contestar 25 de 126 partidas a **70 de
168, con precisión del 100 %** y cobertura del 41.67 %.

Las reglas que se añadieron, cada una con su caso detrás:

| Regla | El caso que la obligó |
|---|---|
| Un CABLE es uno de los «Cables» (#176) | 41 cables sin clasificar porque la ficha dice «CABLE» y la tarifa «Cables» |
| «excepto» niega igual que «sin» (#178) | 301 posiciones usan «excepto» y el motor sólo leía «sin» (369) |
| La ficha también niega (#178) | «CABLE SIN RECUBRIMIENTO» descartaba su propia fracción correcta |
| La materia que opone la tarifa (#172, ADR 0005) | fregadero de acero inoxidable con cuatro subpartidas empatadas |
| Un residual no empata con la específica (#184) | «estropajo» debía ir a 7323.10 y competía con 7323.94 |
| La partida que nombra la materia (#186) | tres cables de acero acababan en 8544, cable eléctrico aislado |
| La ficha niega lo que el texto exige (#186) | 14 vajillas «NO PORCELANA» resolviendo en la 6911, «de porcelana» |
| La respuesta firmada descarta subpartidas (#186) | la olla de presión, con su respuesta ya en la base y sin efecto |

**Lo que no se arregló, y está medido.** La búsqueda de partida sigue siendo
una bolsa de palabras con un tope de seis términos, y tres intentos de
mejorarla la empeoraron: [ADR 0007](adr/0007-la-busqueda-de-partida-no-se-arregla-tocando-terminos.md).
Ocho casos de la bandeja —un sartén y tres «utensilios»— acaban buscando entre
tubos y tornillos porque la tarifa no dice «sartén» en ningún sitio.

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

**La búsqueda es semántica y degrada, no tumba** (PR #68). 2 141 de los 2 144
chunks tienen vector (`text-embedding-3-small`, 1536) y `classify` y el Copilot
los consumen. Los tres sin vector son el único hueco, y es pequeño. Si el proveedor falla —429, timeout, sin llave— la petición no cae:
sigue por término y vigencia, y lo declara en `modo_busqueda`. Verificado con
un 429 simulado contra la base real.

**Las citas son auditables** (PRs #70 y #73). Cada chunk apunta a su fila de
`legal_rules` por la terna (documento, artículo, `valid_from`), y cada
clasificación guarda en `legal_rule_ids` qué normas citó. Con eso el Sentinel
dejó de ser `trazable: false`: **4 745 de las 5 209 decisiones citan sus
normas**. Las que no son las anteriores al #73, que no las guardaban.

### El bucle de captura — de la pregunta al dictamen ✅

Es lo que se cerró el 5 de octubre y lo que convierte el sistema en algo que
aprende. Cuatro piezas:

1. **El motor pregunta.** Cuando se atasca, formula una pregunta de sí o no
   sobre la cláusula que de verdad distingue (#179, #180). Se calla cuando la
   pregunta no se puede contestar mirando la mercancía —una referencia cruzada
   a otra fracción (#189)— y cuando ya se contestó (#190).
2. **Se contesta en la consola.** Pantalla de Revisión: el término de la ficha
   se elige de una lista, no se teclea (#183), porque el primero que lo teclëó
   escribió la etiqueta y su respuesta quedó inerte.
3. **La respuesta entra firmada** en `nomenclature_synonyms` como
   `HUMAN_VALIDATED`, con su `valid_from` ligado a la vigencia de la tarifa, no
   al día en que se contestó.
4. **Y surte efecto.** Contestar reclasifica en segundo plano los casos que
   tenían esa pregunta (#192). Hasta ese PR la respuesta se guardaba y las
   decisiones seguían siendo las de antes: reclasificar era un comando manual.

El veredicto humano cabe entero desde el #187: fracción **y** NICO —son dos
niveles y no deben mezclarse— y un tercer veredicto, `FALTA_INFORMACION`, para
cuando la ficha no alcanza. Sin él la única forma de registrar «pidan el dato,
no inventen una fracción» era inventar una fracción.

```
13 respuestas de vocabulario firmadas
59 veredictos humanos · 36 con NICO · 3 de «falta información»
 3 preguntas vivas que desatascarían 58 casos
```

### `apps/api/` ✅ 23 endpoints · `apps/web/` ✅ 11 pantallas

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

⚠️ **La llave de OpenAI viajó por un chat el 9-sep.** Persona 1 decidió el
23-sep **no rotarla mientras el entorno sea de pruebas**, y cambiarla al pasar
a producción. Ver la decisión y su disparador más abajo.

### Scorecard del §44

```
DATA           6 de 14   LIGIE ✅ (los 97 capítulos, con los textos de cada
                         nivel: ADR 0002) · NICO ✅ · Ley Aduanera ✅ ·
                         Anexo 22 ✅ · RGCE 2026 ✅ · Anexo 2.4.1 ✅ (456
                         correlaciones fracción → NOM, #170)
                         PROSEC ❌ · Regla 8a ❌ · Cuotas ❌ · CBP ❌ ·
                         EBTI ❌ · Banxico ❌ · ANAM/SAT/Data México ❌
CORE           4 de 4    Product DNA ✅ · RGI ✅ · Classification ✅ ·
                         Evidence ✅
SIMULATOR      ✅ cargado  16 pedimentos · 181 partidas · 181 productos ·
                         61 anomalías sembradas. Era el cuello de botella
                         del 21-sep y dejó de serlo.
INTELLIGENCE   5 de 6    Shadow ✅ · Audit ✅ · Money ✅ · Opportunity ✅ ·
                         Sentinel ✅ · Knowledge Graph ⏳ aprobado el 21-sep,
                         sin cerrar
PRODUCT        2.5 de 3  Dashboard ✅ · Copilot ✅ · Demo AJR ⏳ sin fecha
```

### El vertical slice del §42 — cerrado y medido

```
ficha técnica → Product DNA → RGI → Classification → Evidence →
pedimento sintético → Shadow → divergencia → Money Finder
      ✅            ✅        ✅            ✅         ✅
```

Cerrado de punta a punta y **medido contra el corpus** (6-oct):

```
clasificación   168 partidas con fracción fiable
                contestó 70 · acertó 70 · falló 0
                precisión 100.00 % · margen al 95 % ±2.60
                cobertura 41.67 % — cuántas veces se atrevió a contestar
                se abstuvo 98 — el §8.2 funcionando, no un error

detección       TP 50 · FP 0 · FN 5 · TN 126
                precisión 100.00 % · recall 90.91 % (±7.82) · F1 95.24
                cobertura 49 de 55 partidas sucias señaladas por algo
```

**La precisión se mide sobre un ámbito que antes tenía un punto ciego** (#185).
Se medía sólo sobre las 126 partidas limpias, bajo una premisa falsa: que toda
anomalía sembrada toca la fracción. Sólo dos de las siete clases la tocan, así
que 42 partidas quedaban fuera — y entre ellas estaba la peor respuesta del
motor. El titular decía «100 %» y ese caso no contaba. Lo encontró un
clasificador revisando a mano, no la medición.

1 161 tests en verde prueban el motor contra los casos que escribimos nosotros.
Van **cinco** fallos graves que pasaban todos sus tests y sólo aparecieron
ejecutando contra datos reales o contra el criterio de una persona: la RGI 3 c)
que resolvía sin pedir revisión, el reordenamiento que destruía el orden
semántico, el prefiltro sensible a acentos, una exclusión firmada que
descartaba la fracción correcta de otro producto (#177), y una pregunta que al
contestarse daba una fracción equivocada (#191). Todos del mismo tipo: verde en
el repo, equivocado en producción.

### Lo que de verdad falta

| # | Hueco | Por qué importa |
|---|---|---|
| 1 | **La búsqueda de partida, cuando la tarifa no nombra la mercancía** | Ocho casos de la bandeja —un sartén de acero inoxidable y tres «utensilios»— acaban entre tubos y tornillos. La tarifa no dice «sartén» en ningún sitio: `poder_de_discriminacion` le da **cero** posiciones. Tres intentos de arreglarlo midiendo salieron peor ([ADR 0007](adr/0007-la-busqueda-de-partida-no-se-arregla-tocando-terminos.md)). La vía que queda es la que el §27 asigna al RAG, y es un cambio de arquitectura: **pide decisión de Persona 1**. |
| 2 | **El puente de vocabulario no puede ensanchar ninguna búsqueda** | La tabla existe, el endpoint funciona y las respuestas entran firmadas, pero el puente cae siempre fuera del tope de seis términos. Dejarlo pasar costó 29 aciertos, porque además le da un punto de cobertura a la posición de cuyo texto salió. Hace falta que la cobertura distinga un término de la ficha de un puente — toca el puerto `TariffCatalog` y su SQL (#188). |
| 3 | **Cinco fracciones del dictamen no existen en la TIGIE cargada** | `73051901` ×3 y `73051201` ×2. El guardarraíl del veredicto las rechazó —el mismo que impidió aceptar `73239399` para un sartén—. El propio dictamen dice que las fracciones se contrastaron «cuando fue posible» y no lista ninguna de 7305 entre las verificadas. **Hay que preguntárselo al clasificador**, no decidirlo aquí. |
| 4 | **Knowledge Graph** | Aprobado el 21-sep y sin cerrar. Es **proyección de Postgres, nunca fuente**: se reconstruye con MERGE por el id de la fila, y nada que fundamente jurídicamente puede citarse desde ahí. Es lo único que falta de INTELLIGENCE. |
| 5 | **Los identificadores del pedimento** | 174 claves del Anexo 22 cargadas y el Espejo no comprueba ninguna. Necesita las reglas de las RGCE que dicen cuál exige cada fracción. |
| 6 | **Las fuentes vacías** | `anam`, `banxico`, `cbp_cross`, `datamexico`, `ebti`, `sat`, `vucem`, `wco`. Ninguna bloquea el camino crítico hoy. |

### Deuda técnica conocida

- **El historial no se reescribe (Persona 1, 28-sep).** El repositorio pasó a
  público ese día y salieron de él tres documentos que eran material comercial
  sobre un tercero, no documentación técnica. Quedaron fuera del árbol vigente
  —que es lo que ven un navegador, `raw` y los buscadores— y **se conservan
  fuera del repositorio**, porque su análisis sigue siendo correcto.

  Siguen alcanzables para quien sepa que existieron y busque a propósito.
  **Decisión: se acepta.** Sacarlos del historial obligaría a reconstruir 181
  commits, invalidaría los clones de todo el equipo y exigiría un trámite con
  soporte de GitHub, a cambio de cerrar una puerta con la que nadie tropieza
  navegando. Con cero forks y cero watchers al momento de decidirlo, el riesgo
  se consideró menor que el coste.

  **Lo que sí cambia para siempre:** el repositorio es público. Cualquier cosa
  que se suba —commit, mensaje, comentario de PR— es visible al instante y con
  ella no hay segunda oportunidad. Nada de credenciales, direcciones internas
  ni nombres de terceros, ni siquiera de forma temporal.
- **No hay datos reales, y no los va a haber por esta vía.** AJR no entregará
  más pedimentos (Persona 1, 23-sep): por eso el corpus espejo se generó por
  nuestra cuenta y los 16 pedimentos y 181 partidas están marcados `SYNTHETIC`.
  La consecuencia que importa no es la etiqueta —es correcta— sino que el
  número se queda en **detección medida**, nunca en precisión medida.
  **La salida no es conseguir pedimentos: es conseguir un dictamen.** Cuando un
  clasificador revise un caso, esa fila entra como `HUMAN_VALIDATED` y deja de
  ser sintética. **Eso ya pasó**: el 5 de octubre entraron 59 veredictos y 13
  respuestas de vocabulario firmadas por un clasificador real, de dos dictámenes
  suyos sobre el corpus.

  Lo que no cambia: esos veredictos se transcribieron desde dos documentos de
  texto, no se teclearon en la consola. Cada fila lo dice en su nota —«el
  criterio es suyo; el teclado, mío»— porque una fila `HUMAN_VALIDATED` que
  insinúe un rastro de interfaz que no existe vale menos que ninguna.
- **La vigencia de una evidencia no se persiste.** `Evidence.to_row()` no
  emite `valid_from` ni `valid_to`, y `evidence_records` no tiene esas
  columnas, así que el expediente del §49 contesta la vigencia como
  `UNKNOWN → vigente`. La fecha existe cuando se construye la evidencia y se
  pierde al guardarla. Necesita migración —lane de Persona 2, regla 8— y se
  agrava porque `legal_documents.published_at` está NULL en los cuatro
  documentos cargados. Hasta entonces, «¿cuándo era vigente?» se contesta a
  medias.
- **La métrica lee los hallazgos de TODAS las revisiones, no de la última**
  (hallazgo de Persona 1, 23-sep). Eso le permitió tapar un error real: una
  re-auditoría mía con el cuerpo vacío borró los 28 hallazgos de IVA de las
  revisiones vigentes, y la métrica siguió marcando 83.33 % porque contaba los
  del día anterior como aciertos. El número volvió a ser cierto al re-auditar
  con `iva_rate` y `dta_rate`, pero **la métrica debe medir el estado actual, no
  el histórico acumulado**. Va para Persona 3 junto al filtro de `/findings`.
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
  siendo el equivocado. Desde octubre llega mucho menos: las reglas 3 a) por
  materia (#172) y por residual (#184, #191) resuelven antes la mayoría de los
  empates que antes caían aquí.
- **Un patrón que apareció cuatro veces el 5 de octubre: un dato escrito en el
  dominio que nadie vuelve a leer.** El NICO del revisor, la respuesta firmada
  al elegir subpartida, el vocabulario en el generador de preguntas, y
  `poder_de_discriminacion` —medida, documentada y con **una sola aparición en
  todo el repositorio: su propia definición**—. Los tres primeros están
  arreglados; el cuarto está documentado en el ADR 0007 y sigue sin usarse a
  propósito.

  Vale como criterio de revisión: cuando un PR añade una columna, un campo o
  una medida, la pregunta no es si se escribe bien, es **quién la lee**.
- **El ADR 0003 no está en `develop`.** El código (`ingestion/se/anexo_2_4_1.py`
  y `database/models/regulatory.py`) y un PR mergeado (#170) lo citan, y el
  fichero vive sólo en la rama `docs/adr-correlacion-fraccion-nom` de Persona 2,
  del 28-sep, sin PR abierto. Hay tres ramas suyas sin mergear:
  `docs/adr-correlacion-fraccion-nom`, `feat/legal-chunks-legal-rule-id` (9-sep)
  y `fix/corpus-espejo-product-compartido-y-summary` (22-sep).
- **Una fila del seed con `document_refs` vacío** en la compartida. El código
  está arreglado (#67); la fila vieja sigue porque la escritura directa a la
  base quedó bloqueada por permisos.
- `GroundTruthRecord` está diseñado para anomalías inyectadas (§26) y **no
  sirve** para medir acierto de clasificación; esa vía son las filas
  `HUMAN_VALIDATED` que comparten `product_dna_id`.
- **Respaldos: 369 MB en el mismo disco que la base, y la réplica está a un
  paso de cerrarse.** Esta máquina tiene un solo disco, así que sacarlos exige
  otra máquina. `yayo` ya tiene `sshd` levantado (Persona 2, 22-sep) y su
  llave de host está **verificada por un tercero**, no aceptada a ciegas:
  `SHA256:KerxOmVoMMh4gYut/nnpmm8lkmw/3fvKFvNloxWv32M`, confirmada por Persona 2
  con `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` y coincidente con
  `known_hosts`.
  El script ya replica y **verifica la copia por contenido** —segunda pasada con
  `--checksum`, porque un archivo truncado tiene el tamaño correcto— y sale con
  código 3 si no logró salir del disco, en vez de dar un verde falso. Se activa
  con `ADUANERO_BACKUP_REMOTO` en `.env`; sin ella no intenta nada.
  **Al 6 de octubre el bloqueo ya no es la llave: es que la máquina está
  apagada.** Faltaba el `HostName` en `~/.ssh/config` del dev server y se
  añadió; desde entonces el error es `Connection timed out`, no un rechazo de
  autenticación. 369 MB y 21 volcados siguen en el mismo disco que la base.
- **Credenciales expuestas: rotación diferida a producción (Persona 1,
  23-sep).** Tres viajaron por un chat: la llave de OpenAI (9-sep) y las de
  PostgreSQL y Neo4j (22-sep). **Decisión: no se rotan mientras el entorno sea
  de pruebas.** El razonamiento vale para las de infraestructura —viven en una
  red de Tailscale, con datos sintéticos y sin nada de cliente— y para la de
  OpenAI se asume a sabiendas: esa llave no está acotada a un entorno sino a
  una cuenta de facturación, así que el gasto es posible hoy, no en producción.

  **Disparador, no fecha:** se rotan las tres antes de que entre el primer dato
  real de un cliente, que es también cuando `aduanero_app` deja de ser un
  superusuario compartido. Lo que no cambia mientras tanto: ninguna credencial
  nueva vuelve a pasar por un chat, y el rol de sólo lectura que ofreció
  Persona 3 sigue en pie para la métrica.

**Cerrado desde el 14-sep:** el doble veredicto (#79), el tope de olas del
Sentinel (#78), el emparejamiento de la métrica por DNA y tiempo (#81) y la
rama suelta de `legal-chunks-legal-rule-id`.

---

## 8. Backlog por persona

> Al 6 de octubre. `develop` en `72905e2`, 412 commits, 0 PRs abiertos.
> **Los últimos 60 commits son de Persona 1**: la última aportación de Persona 2
> es del 30-sep y la de Persona 3 del 28-sep. Este documento no afirma en qué
> están trabajando — lo de abajo es lo que consta en el repositorio.

### Persona 2 — Brandon (Data Engineer)

| # | Tarea | Estado |
|---|---|---|
| 1 | El cargador del corpus | ✅ cargado: 16 pedimentos, 181 partidas, 61 anomalías |
| 2 | La cadena del proveedor | ✅ la comprobación de país corre sobre el corpus |
| 3 | Niveles intermedios de un guion (ADR 0004) | ✅ 30-sep |
| 4 | **Abrir el PR del ADR 0003** | 🔴 el código lo cita y el fichero está sólo en su rama, del 28-sep |
| 5 | **Cerrar o descartar dos ramas suyas** | 🔴 `feat/legal-chunks-legal-rule-id` (9-sep) y `fix/corpus-espejo-product-compartido-y-summary` (22-sep) |
| 6 | Las reglas de identificadores de las RGCE | 🟡 desbloquea el hueco 5 del §7 |
| 7 | Reconocimiento de CBP CROSS | ⏸ nada depende de ello hoy |

### Persona 3 — Ulises (AI + Full Stack)

| # | Tarea | Estado |
|---|---|---|
| 1 | Métrica de detección (§26) | ✅ corriendo: TP 50 · FP 0 · recall 90.91 % |
| 2 | Los dictámenes humanos como fuente de precisión | ✅ 28-sep, y usada: 59 veredictos |
| 3 | **Knowledge Graph** | 🟡 aprobado el 21-sep, sin cerrar. Lo único que falta de INTELLIGENCE |
| 4 | Harness de `hs_accuracy` contra CBP CROSS | ⏸ baja prioridad: el corpus mide sin depender de nadie |

### Persona 1 — Erick (Tech Lead)

| # | Tarea | Estado |
|---|---|---|
| 1 | **Decidir la búsqueda de partida por significado** | 🔴 es el hueco 1 del §7 y el único que no se puede decidir desde dentro: toca el camino que mide el harness y afecta a los 181 productos |
| 2 | **Preguntar al clasificador las cinco fracciones de 7305** | 🔴 es lo único de sus 49 casos que quedó sin aplicar |
| 3 | **Decidir si la consola se abre en el tailnet** | 🔴 hoy sólo se puede contestar sentado en el dev server |
| 4 | Rotar las tres credenciales expuestas | ⏸ diferido a producción. Disparador: el primer dato real de cliente |
| 5 | Respaldos fuera de esta máquina | ⏸ la máquina de respaldo está apagada |
| 6 | Modelo de negocio y fecha de entrega | ⏸ fuera del alcance de los agentes por decisión suya |

---

## 9. La siguiente tarea

**Decidir cómo se elige la partida cuando la tarifa no nombra la mercancía.**

Todo lo demás del camino crítico está cerrado y medido: el corpus cargado, el
motor con precisión del 100 % sobre 168 partidas, el bucle de captura
funcionando de punta a punta y 59 veredictos de un clasificador real dentro del
sistema. Lo que queda es el techo de la cobertura, y es un techo de
arquitectura, no de ajuste: está medido en el
[ADR 0007](adr/0007-la-busqueda-de-partida-no-se-arregla-tocando-terminos.md)
que tres intentos razonables de moverlo lo empeoraron.

La frase que el proyecto podrá decir el día que se resuelva, y hoy no puede:
*«el motor clasifica el X % de las partidas sin ayuda humana, con precisión
medida contra el dictamen de un clasificador»*. Hoy la mitad de esa frase ya es
verdad —la precisión— y la otra mitad está en 41.67 %.

En paralelo y sin esperar a nadie:

1. **Separar el puente de la cobertura** (hueco 2). Es la diferencia entre una
   mesa de vocabulario que crece y una que se llena de respuestas inertes.
2. **El Knowledge Graph** (hueco 4), lo único que le falta a INTELLIGENCE.
3. **Las cinco fracciones de 7305**, que es una pregunta, no un desarrollo.

## 10. Documentos del repositorio

| Archivo | Qué contiene |
|---|---|
| `docs/00_ADUANERO_OS_PROMPT_MAESTRO.md` | documento rector, 49 secciones |
| `docs/01_PERSONA_1_TECH_LEAD.md` | rol y responsabilidades de P1 |
| `CLAUDE.md` | reglas no negociables para agentes |
| `docs/ACCESO_EQUIPO.md` | credenciales y reglas de inserción |
| `docs/ARRANQUE_EN_OTRA_MAQUINA.md` | levantar el entorno desde cero |
| `docs/ER_DIAGRAM.md` | diagrama Mermaid del modelo |
| `docs/RECONOCIMIENTO_RGCE_2026.md` | reconocimiento de RGCE 2026, antes de cargar |
| `docs/TAREA_P2_CANONICAL_MODEL.md` · `docs/TAREA_P2_CORPUS_JURIDICO.md` | encargos a Persona 2 |
| `docs/TAREA_P3_MODEL_PROVIDER.md` · `docs/TAREA_P3_RAG_INTEGRACION.md` | encargos a Persona 3 |
| `docs/PROMPT_P2.md` · `docs/PROMPT_P3.md` | prompts de arranque para los agentes |
| `apps/evaluacion/corpus_espejo.py` | valida un corpus antes de cargarlo |
| `apps/evaluacion/clasificacion_39.py` | mide precisión y cobertura de la clasificación (§39) |
| `apps/evaluacion/deteccion_26.py` | mide precisión/recall del §26 · `--escenarios` lista los corpus |
| `apps/evaluacion/preguntas_pendientes.py` | qué preguntas desatascarían más casos |
| `infrastructure/scripts/00_INSTALACION.md` | instalación del dev server |

### Decisiones de arquitectura

| ADR | Qué decide |
|---|---|
| [0001](adr/0001-puertos-y-bind-del-dev-server.md) | por qué 8080 y 5433, y nunca `0.0.0.0` |
| [0002](adr/0002-donde-vive-el-texto-de-partidas-y-subpartidas.md) | `regulatory.tariff_headings`, y nada de filas de 4 dígitos en `tariff_fractions` |
| 0003 | correlación fracción → NOM, y es el Anexo 2.4.1. ⚠️ **citado por el código y ausente de `develop`** |
| [0004](adr/0004-niveles-intermedios-de-un-guion.md) | los niveles intermedios de un guion de la LIGIE |
| [0005](adr/0005-la-materia-que-opone-la-tarifa.md) | cuando la tarifa opone dos hermanas por materia, ya decidió |
| [0006](adr/0006-como-se-agrega-el-dinero-de-una-partida.md) | `LINEA_COMPLETA` frente a `UNA_CONTRIBUCION` al sumar impacto |
| [0007](adr/0007-la-busqueda-de-partida-no-se-arregla-tocando-terminos.md) | tres formas medidas de no arreglar la búsqueda de partida |

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
