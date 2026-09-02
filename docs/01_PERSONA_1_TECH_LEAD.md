# ADUANERO OS — PERSONA 1
## Tech Lead + Product Owner + Integration Engineer

**Proyecto:** ADUANERO OS  
**Empresa:** UDATA  
**Rol:** Persona 1 — Líder técnico/producto y desarrollador de integración  
**Modo inicial:** Desarrollo local, equipo de 3 personas  
**Objetivo del MVP:** Construir una demostración técnicamente realista y defendible de la capa de inteligencia aduanera, usando fuentes públicas/oficiales reales y datos operativos sintéticos cuando no exista acceso a datos de AJR.

---

# 1. Misión del rol

Persona 1 es responsable de mantener una sola visión técnica y de producto.

No es únicamente coordinador. También programa, diseña contratos, integra módulos y es dueño de los componentes críticos del dominio.

La responsabilidad principal es evitar que el proyecto se convierta en tres desarrollos independientes.

## Persona 1 es dueño de

- Arquitectura general.
- Modelo de datos canónico.
- Contratos Pydantic/API.
- Integración entre módulos.
- RGI Engine.
- Classification orchestration.
- Pedimento Espejo / Shadow.
- Audit Engine.
- Money Finder.
- Opportunity Finder.
- Evidence contract.
- Revisión de Pull Requests.
- Integración final del MVP.
- Preparación técnica de la demo para AJR.
- Priorización del backlog.
- Aprobación de cualquier cambio de esquema.
- Aprobación de cualquier nueva fuente de datos.

## Persona 1 NO es dueño primario de

- Scraping/ETL de fuentes: **Persona 2**.
- RAG, embeddings, Product DNA y UI: **Persona 3**.
- Mantenimiento diario de crawlers: **Persona 2**.
- Maquetación visual del frontend: **Persona 3**.

---

# 2. Regla estratégica del proyecto

ADUANERO OS debe conservar un núcleo desacoplado.

```text
AJR / ANA
   │
   ▼
Connector / Adapter
   │
   ▼
Canonical Data Model
   │
   ▼
ADUANERO CORE — UDATA
   │
   ├── Classification
   ├── RGI Engine
   ├── Product DNA
   ├── Evidence
   ├── Audit
   ├── Shadow
   ├── Money Finder
   ├── Opportunity Finder
   └── Regulatory Intelligence
```

El objetivo técnico del MVP es que, si mañana AJR entrega acceso a ANA, no tengamos que reescribir el núcleo.

Solo deberá construirse:

```text
ANA -> AJR Connector -> ADUANERO Canonical Model
```

---

# 3. Arquitectura local inicial

La laptop de Persona 1 funcionará inicialmente como host central.

```text
                     LAPTOP PERSONA 1
                    ADUANERO DEV SERVER
                            │
           ┌────────────────┼─────────────────┐
           │                │                 │
           ▼                ▼                 ▼
      PostgreSQL          Neo4j             MinIO
       + pgvector     Knowledge Graph     documentos
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
        ┌──┴───────────────┐
        │                  │
        ▼                  ▼
  Persona 2            Persona 3
  Data Engineer        AI/Full Stack
```

## Stack base

- Python 3.12+
- FastAPI
- PostgreSQL
- pgvector
- Neo4j
- Redis
- MinIO
- Alembic
- SQLAlchemy
- Pydantic
- Docker / Docker Compose
- React + TypeScript
- GitHub privado
- Tailscale

## Regla de seguridad

Nunca exponer PostgreSQL directamente a Internet.

El acceso remoto del equipo será mediante red privada/Tailscale o túnel seguro.

---

# 4. Repositorio

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
├── database/
│   ├── migrations/
│   ├── models/
│   └── seeds/
├── schemas/
├── tests/
├── docs/
├── infrastructure/
│   ├── docker/
│   └── scripts/
├── CLAUDE.md
├── .env.example
├── docker-compose.yml
└── README.md
```

---

# 5. Quién hace las extracciones

**Responsable primario: Persona 2 — Data Engineer.**

Persona 1:

- aprueba la fuente;
- aprueba el contrato;
- revisa la calidad;
- valida que el dataset sirva al producto;
- no mantiene el crawler salvo emergencia.

Persona 3:

- consume los datos normalizados;
- no scrapea por su cuenta una segunda versión de la misma fuente;
- solicita nuevas columnas o metadatos mediante issue/PR.

## Flujo correcto

```text
FUENTE
  │
  ▼
PERSONA 2
RAW -> PARSED -> NORMALIZED -> VALIDATED
  │
  ▼
Canonical Database
  │
  ├──────── Persona 1: reglas/motores
  │
  └──────── Persona 3: IA/RAG/UI
```

---

# 6. Tipos oficiales de origen de datos

Todo registro relevante debe utilizar uno de estos valores:

```text
OFFICIAL
PUBLIC
LICENSED
SYNTHETIC
HUMAN_VALIDATED
```

Nunca presentar `SYNTHETIC` como real.

---

# 7. Fuentes que Persona 1 debe considerar como contratos de entrada

El catálogo completo vive en el documento de Persona 2.

Las fuentes P0/P1 que Persona 1 debe esperar son:

| Fuente | Tipo | Responsable | Uso en Core |
|---|---|---|---|
| LIGIE/TIGIE | OFFICIAL | Persona 2 | clasificación |
| NICO | OFFICIAL | Persona 2 | clasificación |
| Ley Aduanera | OFFICIAL | Persona 2 | fundamento |
| RGCE 2026 | OFFICIAL | Persona 2 | reglas |
| Anexo 22 | OFFICIAL | Persona 2 | Pedimento Espejo |
| DOF | OFFICIAL | Persona 2 | Sentinel/versionado |
| VUCEM | OFFICIAL | Persona 2 | trámites/avisos |
| PROSEC | OFFICIAL | Persona 2 | Opportunity Finder |
| Regla 8a | OFFICIAL | Persona 2 | Opportunity Finder |
| NOM | OFFICIAL | Persona 2 | cumplimiento |
| Cuotas compensatorias | OFFICIAL | Persona 2 | riesgo/costo |
| ANAM | OFFICIAL | Persona 2 | calibración |
| SAT Datos Abiertos | OFFICIAL | Persona 2 | calibración |
| Data México | PUBLIC/OFFICIAL | Persona 2 | calibración |
| Banxico | OFFICIAL | Persona 2 | tipo de cambio |
| CBP CROSS | PUBLIC/OFFICIAL-US | Persona 2 | casos comparables |
| EBTI | PUBLIC/OFFICIAL-EU | Persona 2 | casos comparables |
| WCO | LICENSED/PUBLIC | Persona 2 | HS/Notas/Opiniones |

---

# 8. Canonical Data Model — responsabilidad directa

Persona 1 define el modelo canónico antes de que los demás desarrollen sobre él.

## Entidades mínimas

- Client
- Supplier
- Product
- ProductDNA
- ProductAttribute
- TariffFraction
- NICO
- LegalSource
- LegalDocument
- LegalRule
- EvidenceRecord
- Invoice
- InvoiceItem
- COVE
- Pedimento
- PedimentoItem
- ClassificationDecision
- ClassificationCandidate
- RiskFinding
- OpportunityFinding
- RegulatoryEvent
- SyntheticScenario
- GroundTruthRecord

## Campos transversales mínimos

```text
id
data_origin
source_id
created_at
updated_at
```

## Para regulación

```text
published_at
valid_from
valid_to
source_url
source_document
content_hash
```

## Para decisiones de IA

```text
decision_id
model_provider
model_name
prompt_version
confidence
requires_human_review
evidence[]
```

---

# 9. Módulos que Persona 1 implementará

## 9.1 RGI Engine

Objetivo:

Aplicar una secuencia explícita de evaluación basada en las Reglas Generales de Interpretación.

No se implementa como un único prompt.

```text
Input
 │
RGI1
 │
¿resuelto?
 ├─ sí -> Candidate
 └─ no
     │
    RGI2
     │
    RGI3
     │
    RGI4
     │
    RGI5
     │
    RGI6
```

Cada paso produce:

```text
rule
input_facts
reasoning_summary
source_ids
candidate_codes
status
confidence
```

El LLM puede ayudar a interpretar; el estado y las reglas deben ser trazables.

---

## 9.2 Classification Orchestrator

Entrada:

- ProductDNA
- fecha de operación
- contexto importación/exportación
- documentos
- catálogos normativos vigentes

Salida:

```text
chapter
heading
subheading
fraction
nico
confidence
reasoning
evidence
alternatives
missing_information
requires_human_review
```

---

## 9.3 Pedimento Shadow

El sistema construye una operación esperada independientemente del pedimento declarado.

```text
Expected Operation
vs
Declared Operation
```

Debe detectar al menos:

- fracción;
- NICO;
- país de origen;
- valor;
- identificadores;
- regulaciones;
- contribuciones;
- inconsistencias de SKU.

---

## 9.4 Audit Engine

Clasifica hallazgos:

```text
INFO
LOW
MEDIUM
HIGH
CRITICAL
```

Cada hallazgo:

```text
finding_type
field
declared_value
expected_value
impact
evidence
confidence
```

---

## 9.5 Money Finder

Los cálculos monetarios se hacen con código determinista.

Nunca pedir al LLM:

> calcula el IGI/IVA/recargos y dime el total.

El LLM puede explicar un resultado ya calculado.

---

## 9.6 Opportunity Finder

Buscar:

- PROSEC potencial;
- Regla 8a;
- preferencia arancelaria;
- sobrepagos;
- alternativas permitidas;
- inconsistencias históricas.

En el MVP toda oportunidad debe marcarse:

```text
POTENTIAL
VALIDATED
REJECTED
```

No declarar un beneficio jurídico como definitivo sin revisión.

---

# 10. Git y coordinación

## Ramas

```text
main
└── develop
    ├── feature/...
    ├── fix/...
    └── chore/...
```

## Reglas

1. Nadie trabaja directamente en `main`.
2. Cada tarea debe tener issue.
3. Un PR debe resolver una tarea concreta.
4. Un cambio de DB requiere Alembic.
5. No crear columnas manualmente en PostgreSQL.
6. No romper contratos existentes sin migración/versionado.
7. No mezclar refactor grande con funcionalidad nueva.
8. Toda funcionalidad crítica debe tener tests.
9. Persona 1 aprueba cambios al Canonical Model.
10. Secrets únicamente en `.env`, jamás Git.

---

# 11. Cadencia de trabajo

## Reunión diaria — 15 minutos

Cada persona responde:

1. ¿Qué terminé?
2. ¿Qué estoy haciendo?
3. ¿Qué bloqueo tengo?
4. ¿Cambiaré algún contrato?

## Revisión de integración — 2 veces por semana

Persona 1 prueba:

```text
ingestion
 -> DB
 -> ProductDNA
 -> Classification
 -> Evidence
 -> Shadow
 -> Audit
```

---

# 12. Primera meta vertical

No construir diez pantallas.

Construir primero:

```text
Ficha técnica / imagen
        │
Product DNA
        │
RGI Engine
        │
Classification
        │
Evidence
        │
Pedimento SYNTHETIC
        │
Pedimento Shadow
        │
Divergence
        │
Money Finder
```

Este flujo debe funcionar de punta a punta antes de aumentar el alcance.

---

# 13. Definition of Done — Persona 1

Una tarea no está terminada solo porque "corre".

Debe cumplir:

- código commiteado;
- tests;
- documentación mínima;
- typing;
- logs cuando aplique;
- sin secretos;
- contratos respetados;
- migrations si aplica;
- evidencia del resultado;
- manejo explícito de error;
- datos sintéticos marcados;
- PR revisado.

---

# 14. Primer backlog de Persona 1

## P0 — Infraestructura

- Crear repo.
- Docker Compose.
- PostgreSQL + pgvector.
- Neo4j.
- Redis.
- MinIO.
- FastAPI health check.
- Alembic.
- `.env.example`.
- Tailscale/documentación de acceso.

## P0 — Canonical Model

- Entidades mínimas.
- Migración inicial.
- Pydantic schemas.
- ER diagram.
- Fixtures.

## P0 — Evidence Contract

Definir desde el inicio, no al final.

## P0 — Primer vertical slice

Integrar:

```text
ProductDNA -> Classification -> Evidence
```

## P1

- RGI Engine.
- Pedimento Shadow.
- Audit Engine.
- Money Finder.

---

# 15. Prompt maestro de Persona 1 para Codex / Claude

```text
Eres Principal Software Architect de ADUANERO OS.

Yo soy el Tech Lead y Product Owner.

Tu función es trabajar dentro de la arquitectura existente, no reconstruir
el proyecto libremente.

RESPONSABILIDADES DE ESTA SESIÓN

- arquitectura;
- contratos;
- integración;
- RGI Engine;
- Classification Orchestrator;
- Pedimento Shadow;
- Audit Engine;
- Money Finder;
- Opportunity Finder;
- Evidence.

ANTES DE PROGRAMAR

1. inspecciona los archivos relevantes;
2. identifica contratos existentes;
3. enumera qué archivos necesitas modificar;
4. identifica riesgos de compatibilidad;
5. aplica el cambio mínimo necesario;
6. no reescribas módulos fuera del alcance.

REGLAS

- No inventes fundamento jurídico.
- No inventes fracciones.
- Las afirmaciones jurídicas deben apuntar a fuentes almacenadas.
- No uses datos futuros para evaluar operaciones históricas.
- Todo dato debe distinguir OFFICIAL, PUBLIC, LICENSED, SYNTHETIC o HUMAN_VALIDATED.
- SYNTHETIC nunca se presenta como real.
- Los cálculos financieros/fiscales importantes son código determinista.
- El LLM interpreta y explica; no sustituye cálculos deterministas.
- Toda decisión debe poder producir EvidenceRecord.
- No cambies DB sin Alembic.
- No hardcodees secretos.
- Agrega pruebas.
- Mantén type hints.

AL TERMINAR REPORTA

ARCHIVOS MODIFICADOS
DECISIONES DE ARQUITECTURA
PRUEBAS
RESULTADOS
RIESGOS
DEUDA TÉCNICA
SIGUIENTE TAREA RECOMENDADA
```

---

# 16. Prompt — Canonical Model

```text
TAREA: Crear el Canonical Data Model de ADUANERO OS.

Diseña modelos Pydantic y SQLAlchemy para:

Client
Supplier
Product
ProductDNA
ProductAttribute
TariffClassification
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
RiskFinding
OpportunityFinding
RegulatoryEvent
SyntheticScenario
GroundTruthRecord

Todo objeto transaccional deberá soportar:

data_origin
created_at
updated_at
source_id

Los objetos regulatorios:

published_at
valid_from
valid_to
source_url
source_document
content_hash

ProductDNA debe distinguir:

OBSERVED
EXTRACTED
INFERRED
MISSING

No implementes aún la lógica completa de clasificación.

Incluye:

- ER diagram Mermaid;
- modelos Pydantic;
- SQLAlchemy;
- migración Alembic;
- fixtures;
- tests.
```

---

# 17. Prompt — RGI Engine

```text
TAREA: Implementar RGI Engine v0.1.

Objetivo:
crear una máquina de evaluación trazable para las Reglas Generales de
Interpretación aplicables a clasificación.

No implementes un único prompt monolítico.

Crea una interfaz común:

RGIRule.evaluate(context) -> RGIResult

RGIResult debe incluir:

rule_id
status
input_facts
candidate_codes
reasoning_summary
source_ids
confidence
missing_information

Estados:

RESOLVED
CONTINUE
INSUFFICIENT_INFORMATION
HUMAN_REVIEW_REQUIRED

Nunca cites conocimiento interno del LLM como fundamento.

Incluye tests unitarios con casos sintéticos y mocks de legal sources.
```

---

# 18. Prompt — Pedimento Shadow

```text
TAREA: Implementar Pedimento Shadow v0.1.

Construye una representación ExpectedPedimento a partir de:

ProductDNA
ClassificationDecision
Invoice
COVE
regulación vigente
catálogos Anexo 22

Compara contra Pedimento declarado.

Devuelve diferencias estructuradas:

field
declared_value
expected_value
severity
source_ids
confidence
requires_human_review

Implementa inicialmente:

FRACTION_MISMATCH
NICO_MISMATCH
ORIGIN_MISMATCH
MISSING_NOM
IDENTIFIER_MISMATCH
VALUE_MISMATCH
INCONSISTENT_SKU_CLASSIFICATION

No inventes obligaciones que no existan en el dataset normativo.

Incluye tests usando GroundTruthRecord de synthetic/.
```

---

# 19. Prompt — Money Finder

```text
TAREA: Implementar Money Finder v0.1.

Recibe un RiskFinding validado suficientemente por reglas y calcula
impacto económico mediante funciones deterministas.

No delegues matemáticas al LLM.

Cada cálculo debe exponer:

formula
inputs
result
currency
calculation_version
source_ids
assumptions
is_simulation

Si algún dato es SYNTHETIC, el resultado debe marcar is_simulation=true.

Incluye tests con Decimal y evita float para dinero.
```

---

# 20. Entregable final esperado de Persona 1

Al terminar el MVP, Persona 1 debe poder ejecutar una demo local completa:

```bash
docker compose up -d
```

y posteriormente demostrar:

1. carga de producto;
2. Product DNA;
3. clasificación;
4. Evidence;
5. pedimento sintético;
6. Pedimento Shadow;
7. hallazgo;
8. impacto monetario;
9. consulta desde dashboard.

El MVP debe dejar claramente visible cuándo un elemento es:

- REAL/OFICIAL;
- PÚBLICO;
- LICENCIADO;
- SINTÉTICO;
- VALIDADO POR HUMANO.
