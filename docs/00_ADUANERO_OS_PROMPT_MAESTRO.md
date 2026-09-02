# ADUANERO OS — PROMPT MAESTRO
## Documento rector para Claude Code / Codex / agentes de desarrollo

**Proyecto:** ADUANERO OS  
**Empresa:** UDATA  
**Modo inicial:** Desarrollo local  
**Equipo:** 3 personas  
**Objetivo:** Construir un MVP técnicamente serio de una plataforma de inteligencia para comercio exterior mexicano, utilizando datos normativos reales y datos operativos sintéticos mientras no exista acceso a información real de AJR.

---

# 1. CONTEXTO DEL PROYECTO

ADUANERO OS no es únicamente un clasificador arancelario.

Es una capa de inteligencia para comercio exterior que debe ser capaz de:

1. Entender mercancías mediante Product DNA.
2. Clasificar mercancías aplicando las Reglas Generales de Interpretación.
3. Sustentar decisiones con evidencia verificable.
4. Construir un Pedimento Espejo.
5. Comparar lo esperado contra lo declarado.
6. Detectar riesgos.
7. Encontrar oportunidades de ahorro.
8. Calcular impacto económico.
9. Vigilar modificaciones regulatorias.
10. Relacionar cambios regulatorios con productos y operaciones.
11. Permitir consultas mediante IA.
12. Construir un historial de decisiones reutilizable.
13. Funcionar posteriormente sobre información proveniente de ANA/AJR sin reescribir el núcleo.

La visión del producto es:

> Convertir información aduanera en decisiones trazables, explicables y económicamente accionables.

---

# 2. OBJETIVO ESTRATÉGICO

El MVP debe ser suficientemente sólido para demostrar a AJR que UDATA no está presentando una idea o una maqueta.

Debe demostrar una plataforma real que puede conectarse posteriormente con ANA.

La arquitectura debe permitir:

```text
AJR / ANA
    │
    ▼
AJR Connector
    │
    ▼
Canonical Data Model
    │
    ▼
ADUANERO CORE
```

ADUANERO CORE debe permanecer desacoplado de ANA.

No construir lógica específica de AJR dentro del motor central.

---

# 3. PRINCIPIO DE PROPIEDAD INTELECTUAL

El núcleo tecnológico de ADUANERO OS pertenece a UDATA.

Incluye:

```text
Classification Engine
RGI Engine
Product DNA
RAG
Knowledge Graph
Evidence Engine
Audit Engine
Pedimento Shadow
Money Finder
Opportunity Finder
Regulatory Intelligence
Agent Orchestration
Evaluation Framework
```

La integración futura con AJR debe ocurrir mediante:

```text
API
connector
adapter
SDK
white-label
```

No mezclar el núcleo con código específico de ANA.

---

# 4. EQUIPO

## PERSONA 1

### Tech Lead + Product Owner + Integration Engineer

Responsable de:

```text
arquitectura
Canonical Data Model
contratos
RGI Engine
Classification Orchestrator
Pedimento Shadow
Audit Engine
Money Finder
Opportunity Finder
integración
Pull Requests
demo AJR
```

También programa.

---

## PERSONA 2

### Senior Data Engineer

Responsable de:

```text
extracciones
crawlers
APIs
ETL
RAW storage
normalización
versionado
PostgreSQL
calidad
DOF Regulatory Watcher
datos sintéticos
Ground Truth
```

**Persona 2 es responsable de todas las extracciones de fuentes externas.**

---

## PERSONA 3

### Senior AI Engineer + Full Stack Engineer

Responsable de:

```text
Product DNA
LLM abstraction
multimodal
RAG
embeddings
Knowledge Graph
Copilot
Evidence UI
frontend
dashboard
human review UI
```

---

# 5. ARQUITECTURA INICIAL

La laptop de Persona 1 funciona inicialmente como servidor de desarrollo.

```text
                     LAPTOP PERSONA 1
                    ADUANERO DEV SERVER
                            │
           ┌────────────────┼────────────────┐
           │                │                │
           ▼                ▼                ▼
      PostgreSQL          Neo4j            MinIO
       + pgvector     Knowledge Graph    documentos
           │
           ├──────────── Redis
           │
           ▼
         FastAPI
           │
           ▼
      ADUANERO CORE
           │
        Tailscale
           │
        ┌──┴───────────┐
        │              │
        ▼              ▼
    PERSONA 2       PERSONA 3
```

---

# 6. STACK

Backend:

```text
Python 3.12+
FastAPI
Pydantic
SQLAlchemy
Alembic
```

Datos:

```text
PostgreSQL
pgvector
Neo4j
Redis
MinIO
```

Frontend:

```text
React
TypeScript
Vite
```

Infraestructura:

```text
Docker
Docker Compose
GitHub privado
Tailscale
```

IA:

```text
OpenAI
Anthropic
Gemini
modelos locales cuando convenga
```

Nunca acoplar lógica de dominio directamente a un proveedor.

---

# 7. ESTRUCTURA DEL REPOSITORIO

```text
ADUANERO_OS/
│
├── apps/
│   ├── api/
│   └── web/
│
├── core/
│   ├── classification/
│   ├── rgi_engine/
│   ├── product_dna/
│   ├── evidence/
│   ├── taxation/
│   ├── audit/
│   ├── shadow/
│   └── opportunity/
│
├── ingestion/
│   ├── snice/
│   ├── dof/
│   ├── vucem/
│   ├── sat/
│   ├── anam/
│   ├── datamexico/
│   ├── banxico/
│   ├── cbp_cross/
│   ├── ebti/
│   └── wco/
│
├── rag/
├── graph/
├── synthetic/
│
├── database/
│   ├── migrations/
│   ├── models/
│   └── seeds/
│
├── schemas/
├── prompts/
├── tests/
├── docs/
│
├── infrastructure/
│   ├── docker/
│   └── scripts/
│
├── CLAUDE.md
├── .env.example
├── docker-compose.yml
└── README.md
```

---

# 8. PRINCIPIOS NO NEGOCIABLES

## 8.1 Nunca inventar fundamento jurídico

Prohibido:

```text
"Según la ley..."
```

si no existe una fuente recuperada.

Toda conclusión jurídica debe poder relacionarse con:

```text
source_id
document
article/rule
publication_date
validity
content_hash
```

---

## 8.2 Nunca inventar una fracción

Si no existe información suficiente:

```text
INSUFFICIENT_INFORMATION
```

o:

```text
HUMAN_REVIEW_REQUIRED
```

---

# 9. DATOS: TIPOS DE ORIGEN

Todo dato relevante debe tener:

```text
data_origin
```

Valores permitidos:

```text
OFFICIAL
PUBLIC
LICENSED
SYNTHETIC
HUMAN_VALIDATED
```

Nunca crear otros valores sin aprobación de Persona 1.

---

# 10. DATOS SINTÉTICOS

Mientras AJR no entregue datos reales, se utilizarán datos sintéticos.

Los datos sintéticos incluirán:

```text
clientes
proveedores
productos
facturas
COVE
pedimentos
partidas
rectificaciones
errores
hallazgos
```

Todos deben contener:

```text
data_origin = SYNTHETIC
synthetic_scenario_id
seed
```

Nunca presentar estos datos como reales.

---

# 11. FUENTES REALES DEL PROYECTO

Persona 2 mantiene el catálogo operativo completo.

Fuentes iniciales:

---

## LIGIE / TIGIE

https://www.diputados.gob.mx/LeyesBiblio/ref/ligie_2022.htm

Complementaria:

https://www.snice.gob.mx/cs/avi/snice/ligie.info22.html

Uso:

```text
clasificación
arancel
vigencia
```

---

## NICO

https://www.snice.gob.mx/cs/avi/snice/ligie.nico2022.html

Uso:

```text
NICO
descripciones
correlaciones
vigencias
```

---

## Ley Aduanera

https://www.diputados.gob.mx/LeyesBiblio/ref/ladua.htm

Uso:

```text
RAG jurídico
fundamentos
```

---

## RGCE 2026

https://dof.gob.mx/nota_detalle_popup.php?codigo=5777199

Uso:

```text
reglas de comercio exterior
```

---

## Anexo 22

https://www.dof.gob.mx/abrirPDF.php?anio=2026&archivo=15012026-MAT.pdf

Uso:

```text
modelo de pedimento
claves
identificadores
catálogos
```

---

## DOF

https://www.dof.gob.mx/

Uso:

```text
Regulatory Watcher
cambios legales
vigencias
```

---

## VUCEM

https://www.ventanillaunica.gob.mx/vucem/

Uso:

```text
procedimientos
avisos
documentación
```

---

## PROSEC

https://www.snice.gob.mx/cs/avi/snice/programasdefom.prosec.html

Uso:

```text
Opportunity Finder
beneficios potenciales
```

---

## Regla 8a

https://www.snice.gob.mx/cs/avi/snice/sectores_mx_regla8va.html

Uso:

```text
Opportunity Finder
```

---

## Cuotas compensatorias

https://www.snice.gob.mx/cs/avi/snice/drrnas.cuotascomp.html

Uso:

```text
Risk Engine
landed cost
```

---

## NOM

https://www.snice.gob.mx/cs/avi/snice/drrnas.noms.acercade.html

Uso:

```text
cumplimiento
Pedimento Shadow
```

---

## SAT Datos Abiertos

https://www.sat.gob.mx/minisitio/DatosAbiertos/dyp.html

Uso:

```text
calibración estadística
synthetic generator
```

---

## ANAM

https://www.anam.gob.mx/estadisticas-anam/

https://www.anam.gob.mx/operaciones-pedimentos-y-valor-de-las-mercancias/

https://www.anam.gob.mx/informe-mensual/

Uso:

```text
calibración
benchmarks
estadísticas
```

---

## Data México

https://www.economia.gob.mx/datamexico/es

https://www.economia.gob.mx/datamexico/es/about/infoapi

Uso:

```text
distribuciones de comercio
países
productos
valores
synthetic generator
```

---

## Banxico

https://www.banxico.org.mx/SieAPIRest/swagger/index.html

Uso:

```text
tipo de cambio
FIX
cálculos históricos
```

---

## CBP CROSS

https://rulings.cbp.gov/

Uso:

```text
casos internacionales comparables
producto -> HS6 -> razonamiento
```

No convertir automáticamente HTS10 a TIGIE.

---

## EBTI

https://taxation-customs.ec.europa.eu/online-services/online-services-and-databases-customs/european-binding-tariff-information-ebti_en

Uso:

```text
casos comparables internacionales
```

No convertir CN/TARIC directamente a clasificación mexicana.

---

## WCO

https://www.wcoomd.org/en/topics/nomenclature/instrument-and-tools/tools-to-assist-with-the-classification-in-the-hs/explanatory-notes.aspx

Uso:

```text
HS
Explanatory Notes
Classification Opinions
```

Contenido premium:

```text
LICENSE_REVIEW_REQUIRED
```

No scrapear contenido restringido.

---

# 12. PIPELINE DE EXTRACCIÓN

Toda extracción debe seguir:

```text
SOURCE
  ↓
RAW
  ↓
PARSED
  ↓
NORMALIZED
  ↓
VALIDATED
  ↓
DATABASE
```

Nunca saltarse RAW.

---

# 13. METADATOS DE EXTRACCIÓN

Cuando sea posible cada registro/documento debe guardar:

```text
source_name
source_url
source_document
source_version
retrieved_at
published_at
valid_from
valid_to
content_hash
data_origin
```

---

# 14. VERSIONADO TEMPORAL

Nunca evaluar una operación histórica con una regulación futura.

Ejemplo:

Operación:

```text
2024-03-15
```

Consulta legal:

```text
valid_from <= 2024-03-15
AND
(valid_to IS NULL OR valid_to >= 2024-03-15)
```

---

# 15. CANONICAL DATA MODEL

Entidades mínimas:

```text
Client
Supplier
Product
ProductDNA
ProductAttribute
TariffFraction
NICO
LegalSource
LegalDocument
LegalRule
EvidenceRecord
Invoice
InvoiceItem
COVE
Pedimento
PedimentoItem
ClassificationDecision
ClassificationCandidate
RiskFinding
OpportunityFinding
RegulatoryEvent
SyntheticScenario
GroundTruthRecord
```

---

# 16. PRODUCT DNA

Entrada:

```text
texto
PDF
imagen
factura
ficha técnica
manual
datasheet
```

Salida:

```text
product_name
commercial_name
manufacturer
brand
model
sku
function
materials
composition
dimensions
weight
voltage
power
capacity
industry
intended_use
country_of_manufacture
technical_attributes
missing_information
```

Cada atributo:

```text
value
status
confidence
evidence_reference
```

Estados:

```text
OBSERVED
EXTRACTED
INFERRED
MISSING
```

---

# 17. EVIDENCE

Toda decisión importante debe tener evidencia.

Ejemplo:

```text
Decision ID
AD-2026-000001

classification
confidence
RGI applied
source IDs
documents
model
prompt version
engine version
content hashes
human review
```

---

# 18. RGI ENGINE

No implementar clasificación como un prompt gigante.

Construir una máquina de evaluación.

```text
RGI 1
 ↓
¿resuelto?
 ├── sí
 │
 └── no
      ↓
     RGI 2
      ↓
     RGI 3
      ↓
     RGI 4
      ↓
     RGI 5
      ↓
     RGI 6
```

Interfaz:

```python
RGIRule.evaluate(context) -> RGIResult
```

Resultado:

```text
rule_id
status
input_facts
candidate_codes
reasoning_summary
source_ids
confidence
missing_information
```

Estados:

```text
RESOLVED
CONTINUE
INSUFFICIENT_INFORMATION
HUMAN_REVIEW_REQUIRED
```

---

# 19. CLASSIFICATION ENGINE

Input:

```text
ProductDNA
operation_date
legal context
tariff tree
NICO
comparable cases
```

Output:

```text
chapter
heading
subheading
fraction
nico
confidence
reasoning
alternatives
evidence
missing_information
human_review
```

---

# 20. PEDIMENTO SHADOW

Construye lo esperado independientemente de lo declarado.

```text
DECLARED
      VS
EXPECTED
```

Comparar inicialmente:

```text
fracción
NICO
origen
valor
NOM
identificadores
consistencia histórica de SKU
```

---

# 21. AUDIT ENGINE

Hallazgos:

```text
INFO
LOW
MEDIUM
HIGH
CRITICAL
```

Estructura:

```text
finding_type
field
declared_value
expected_value
severity
confidence
source_ids
impact
human_review
```

---

# 22. MONEY FINDER

Los cálculos monetarios deben ser deterministas.

Nunca usar el LLM como calculadora fiscal.

Usar:

```text
Decimal
```

y nunca `float` para dinero.

Toda salida:

```text
formula
inputs
result
currency
calculation_version
assumptions
source_ids
is_simulation
```

---

# 23. OPPORTUNITY FINDER

Buscar potencialmente:

```text
PROSEC
Regla 8a
preferencias
sobrepagos
oportunidades de corrección
alternativas permitidas
```

Estados:

```text
POTENTIAL
VALIDATED
REJECTED
```

Nunca presentar `POTENTIAL` como ahorro garantizado.

---

# 24. SYNTHETIC CUSTOMS GENERATOR

Componentes:

```text
CompanyGenerator
SupplierGenerator
ProductGenerator
InvoiceGenerator
COVEGenerator
PedimentoGenerator
ErrorInjector
GroundTruthGenerator
```

---

# 25. ESCENARIOS DE ERROR

Implementar inicialmente:

```text
WRONG_FRACTION
WRONG_NICO
WRONG_ORIGIN
MISSING_NOM
MISSED_PROSEC
MISSED_PREFERENCE
WRONG_VALUE
MISSING_INCREMENTABLE
WRONG_IDENTIFIER
INCONSISTENT_SKU_CLASSIFICATION
```

---

# 26. GROUND TRUTH

Cada anomalía:

```text
scenario_id
pedimento_id
item_id
error_type
original_value
mutated_value
expected_detection
expected_field
expected_severity
seed
```

Esto permite medir:

```text
precision
recall
false positives
false negatives
```

---

# 27. RAG

Nunca usar:

```text
PDF
 ↓
LLM
 ↓
respuesta
```

Usar:

```text
normalized documents
       ↓
chunking
       ↓
metadata
       ↓
full text
+
vector
+
graph
       ↓
retrieval
       ↓
LLM
       ↓
Evidence-backed response
```

---

# 28. KNOWLEDGE GRAPH

Nodos iniciales:

```text
Product
SKU
Manufacturer
Supplier
Country
TariffFraction
NICO
LegalRule
NOM
PROSECSector
Treaty
Pedimento
Evidence
RegulatoryEvent
```

Relaciones:

```text
PRODUCT --CLASSIFIED_AS--> FRACTION
FRACTION --HAS_NICO--> NICO
FRACTION --SUBJECT_TO--> NOM
FRACTION --AFFECTED_BY--> REGULATORY_EVENT
PRODUCT --SUPPLIED_BY--> SUPPLIER
SUPPLIER --LOCATED_IN--> COUNTRY
DECISION --SUPPORTED_BY--> EVIDENCE
SKU --APPEARS_IN--> PEDIMENTO
```

---

# 29. MODEL PROVIDER ABSTRACTION

No importar SDK específico dentro de dominio.

Crear:

```python
class ModelProvider:
    def generate(...)
    def generate_structured(...)
    def embed(...)
    def analyze_image(...)
```

Adaptadores:

```text
OpenAIProvider
AnthropicProvider
GeminiProvider
LocalProvider
```

---

# 30. PROMPTS

Todos los prompts del producto deben versionarse.

```text
prompts/
├── product_dna/
├── classification_support/
├── legal_extraction/
├── copilot/
└── regulatory_analysis/
```

Registrar:

```text
prompt_id
prompt_version
```

---

# 31. COPILOT

Respuesta estructurada:

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

Si no existe evidencia suficiente:

```text
No tengo evidencia suficiente en la base cargada.
```

Nunca inventar citas.

---

# 32. FRONTEND

Pantallas iniciales:

```text
Executive Dashboard
Product DNA
Classification
Pedimento Shadow
Finding Detail
Regulatory Sentinel
Copilot
```

---

# 33. DATOS SINTÉTICOS EN UI

Si una operación es dummy mostrar claramente:

```text
SYNTHETIC DEMO DATA
```

Las fuentes jurídicas oficiales pueden mostrar:

```text
OFFICIAL SOURCE
```

Mensaje conceptual de la demo:

> Operación simulada. Motor y fuentes reales.

---

# 34. GIT

Ramas:

```text
main
└── develop
    ├── feature/*
    ├── fix/*
    └── chore/*
```

Reglas:

1. nunca desarrollar directo sobre main;
2. cada cambio relevante debe tener PR;
3. cambios de DB requieren Alembic;
4. no crear columnas manuales en PostgreSQL;
5. no hardcodear secrets;
6. no mezclar múltiples features en un PR;
7. agregar tests;
8. Persona 1 aprueba cambios a contratos.

---

# 35. REGLAS PARA CLAUDE / CODEX

Antes de programar:

1. inspecciona el repositorio;
2. identifica lo que ya existe;
3. identifica contratos;
4. lista los archivos que modificarás;
5. no reescribas módulos innecesarios;
6. implementa la solución mínima correcta;
7. ejecuta pruebas;
8. reporta resultados.

---

# 36. REGLA DE NO INVENCIÓN

Cuando no conozcas algo:

NO HACER:

```text
asumir
inventar endpoint
inventar regla
inventar tabla
inventar código arancelario
inventar fuente
```

HACER:

```text
NEEDS_VALIDATION
UNKNOWN
SOURCE_NOT_AVAILABLE
HUMAN_REVIEW_REQUIRED
```

---

# 37. OBSERVABILIDAD

Cada pipeline y motor importante debe producir logs estructurados.

Idealmente:

```text
run_id
module
started_at
finished_at
status
duration_ms
records
errors
model
prompt_version
```

---

# 38. TESTS

Tipos:

```text
unit
integration
contract
data quality
evaluation
```

No depender exclusivamente de pruebas manuales.

---

# 39. EVALUACIÓN DE IA

## Product DNA

Medir:

```text
field extraction accuracy
hallucinated attribute rate
evidence coverage
missing information detection
```

## RAG

```text
retrieval hit rate
source precision
unsupported answer rate
```

## Classification

Con Ground Truth:

```text
HS accuracy
fraction accuracy
NICO accuracy
human review rate
```

## Audit

```text
precision
recall
false positive rate
```

---

# 40. SEGURIDAD

Nunca guardar:

```text
API keys
passwords
tokens
database credentials
```

en Git.

Usar:

```text
.env
.env.example
```

Solo `.env.example` se versiona.

---

# 41. BASE DE DATOS CENTRAL

La base inicialmente vive en la laptop de Persona 1.

Personas 2 y 3 acceden por red privada.

Nunca abrir PostgreSQL públicamente mediante port forwarding.

---

# 42. PRIMER VERTICAL SLICE

Antes de construir múltiples módulos, lograr:

```text
FUENTE REAL
   ↓
TIGIE / NICO / RGCE
   ↓
PRODUCTO
   ↓
PRODUCT DNA
   ↓
RGI ENGINE
   ↓
CLASSIFICATION
   ↓
EVIDENCE
   ↓
PEDIMENTO SYNTHETIC
   ↓
PEDIMENTO SHADOW
   ↓
DIVERGENCE
   ↓
MONEY FINDER
```

Debe funcionar extremo a extremo.

---

# 43. ORDEN DE CONSTRUCCIÓN

## Sprint 0

```text
repo
Docker
PostgreSQL
Neo4j
MinIO
Redis
FastAPI
Alembic
```

## Sprint 1

```text
LIGIE
NICO
Ley Aduanera
RGCE
Anexo 22
```

## Sprint 2

```text
Product DNA
RAG base
Evidence
```

## Sprint 3

```text
RGI Engine
Classification
```

## Sprint 4

```text
Synthetic Generator
```

## Sprint 5

```text
Pedimento Shadow
Audit
Money Finder
```

## Sprint 6

```text
DOF Watcher
Sentinel
Opportunity Finder
```

## Sprint 7

```text
Copilot
Dashboard
Demo AJR
```

---

# 44. SCORECARD

```text
DATA
[ ] LIGIE
[ ] NICO
[ ] Ley Aduanera
[ ] RGCE
[ ] Anexo 22
[ ] DOF
[ ] PROSEC
[ ] Regla 8a
[ ] NOM
[ ] Cuotas
[ ] CBP
[ ] EBTI
[ ] Banxico
[ ] ANAM / SAT / Data México

CORE
[ ] Product DNA
[ ] RGI Engine
[ ] Classification
[ ] Evidence

SIMULATOR
[ ] Client
[ ] Supplier
[ ] Product
[ ] Invoice
[ ] COVE
[ ] Pedimento
[ ] Error Injector
[ ] Ground Truth

INTELLIGENCE
[ ] Shadow
[ ] Audit
[ ] Money Finder
[ ] Opportunity Finder
[ ] Sentinel
[ ] Knowledge Graph

PRODUCT
[ ] Dashboard
[ ] Copilot
[ ] Demo AJR
```

---

# 45. DEFINITION OF DONE GLOBAL

Una tarea no está terminada solo porque el código ejecuta.

Debe incluir cuando aplique:

```text
código
tests
typing
logs
documentación
error handling
trazabilidad
migrations
evidence
data origin
source metadata
security review
```

---

# 46. FORMATO DE REPORTE OBLIGATORIO DEL AGENTE

Al finalizar cada tarea, Claude/Codex debe responder:

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

---

# 47. PROMPT OPERATIVO BASE PARA CUALQUIER TAREA

Usar este bloque antes de agregar una tarea específica:

```text
Lee primero el archivo 00_ADUANERO_OS_PROMPT_MAESTRO.md y el documento correspondiente
a tu rol.

No programes hasta entender:

- arquitectura;
- contratos;
- ownership del módulo;
- fuentes disponibles;
- reglas de datos;
- restricciones jurídicas;
- Definition of Done.

Después inspecciona el repositorio real.

No asumas que una carpeta, tabla o función existe.

No reconstruyas arquitectura ya definida.

Trabaja únicamente dentro del alcance indicado en la tarea.

Si necesitas cambiar un contrato central, detente y marca:

ARCHITECTURE_DECISION_REQUIRED

Si una fuente o regla no puede verificarse:

NEEDS_VALIDATION

Nunca inventes información para completar el flujo.
```

---

# 48. PRIMERA META DEL PROYECTO

El MVP debe demostrar un caso completo:

```text
Usuario carga:
ficha técnica + imagen
        ↓
Aduanero genera:
Product DNA
        ↓
Clasifica:
HS / TIGIE / NICO
        ↓
Explica:
RGI + Evidence
        ↓
Compara:
Pedimento sintético
        ↓
Detecta:
divergencia
        ↓
Calcula:
impacto económico simulado
        ↓
Muestra:
evidencia + fuentes + confianza
```

La demo debe dejar absolutamente claro:

```text
DATOS OPERATIVOS = SYNTHETIC DEMO DATA

FUENTES JURÍDICAS = OFFICIAL / PUBLIC / LICENSED

MOTOR = REAL
```

---

# 49. PRINCIPIO FINAL

La meta no es producir una aplicación que "parezca inteligente".

La meta es construir un sistema que pueda responder:

```text
¿QUÉ DETECTASTE?

¿POR QUÉ?

¿CON QUÉ REGLA?

¿CON QUÉ FUENTE?

¿QUÉ VERSIÓN DE ESA FUENTE?

¿CUÁNDO ERA VIGENTE?

¿QUÉ DATO UTILIZASTE?

¿CUÁNTA CONFIANZA TIENES?

¿CUÁNTO DINERO REPRESENTA?

¿REQUIERE REVISIÓN HUMANA?
```

Si ADUANERO OS no puede responder esas preguntas, la funcionalidad todavía no está terminada.
