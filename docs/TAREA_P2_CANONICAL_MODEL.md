# TAREA — Canonical Data Model v0.1

**Asignada a:** Persona 2  
**Aprueba:** Persona 1 (§8 y §10.9 — el Canonical Model es contrato central)  
**Rama:** `feature/canonical-model`  
**Entrega:** Pull Request contra `develop`. **No apliques la migración a la base
compartida hasta que Persona 1 apruebe el PR.** Pruébala contra una base local
tuya.

---

## 0. Antes de escribir una línea

Lee, en este orden:

1. `docs/00_ADUANERO_OS_PROMPT_MAESTRO.md` — completo.
2. `docs/01_PERSONA_1_TECH_LEAD.md` §8 y §16.
3. `CLAUDE.md` — reglas no negociables.
4. `database/models/base.py` — la convención de constraints ya está definida.

Después inspecciona el repositorio real. No asumas que existe nada.

---

## 1. Alcance

Modelar las entidades del Canonical Data Model. **Sólo el modelo**: nada de
lógica de clasificación, ni de RGI, ni de extracción.

### Base de datos

| | |
|---|---|
| Host | `100.86.182.104` (Tailscale) o `localhost` en el dev server |
| **Puerto** | **5433** |
| Base | `aduanero` |
| Usuario | `aduanero_app` |

⚠️ **En el puerto 5432 hay un PostgreSQL nativo de OTRO proyecto. No lo toques,
ni para leer.** Nuestra base es la del contenedor `aduanero-postgres`, en 5433.

---

## 2. Nomenclatura — obligatoria, no la reinventes

### Esquemas

| Esquema | Qué vive ahí |
|---|---|
| `regulatory` | LIGIE, NICO, Ley Aduanera, RGCE, Anexo 22, NOM, PROSEC, DOF. `data_origin` ∈ OFFICIAL / PUBLIC / LICENSED |
| `operational` | clientes, proveedores, productos, facturas, COVE, pedimentos. Hoy SYNTHETIC |
| `intelligence` | decisiones, evidencia, hallazgos, oportunidades |
| `raw` | landing de ingestión sin transformar |
| `public` | sólo lo genuinamente transversal |

### Reglas de nombres

| Elemento | Regla | Ejemplo |
|---|---|---|
| Tabla | `snake_case`, **plural** | `tariff_fractions`, `legal_documents` |
| Columna | `snake_case`, singular | `commercial_name` |
| Clave primaria | siempre `id`, `UUID`, `DEFAULT gen_random_uuid()` | `id` |
| Clave foránea | `<tabla_en_singular>_id` | `product_id`, `legal_document_id` |
| Booleano | prefijo `is_` / `has_` / `requires_` | `is_simulation`, `requires_human_review` |
| Timestamp | sufijo `_at`, **siempre `TIMESTAMPTZ`** | `created_at`, `retrieved_at` |
| Fecha sin hora | `DATE` | `valid_from`, `valid_to` |
| Dinero | `NUMERIC(18,6)` + columna hermana `<campo>_currency CHAR(3)` | `customs_value`, `customs_value_currency` |
| Porcentaje / tasa | `NUMERIC(9,6)` como fracción (0.16, no 16) | `igi_rate` |
| Enumerado | `VARCHAR` + `CHECK`, vía `sa.Enum(..., native_enum=False)` | ver §3 |
| Índice / constraint | los genera la convención de `database/models/base.py` | — |

**Nada de `FLOAT` ni `REAL` para dinero, tasas o cantidades.** `NUMERIC`
siempre; en Python, `Decimal` (§22 del maestro).

**Nada de enums nativos de PostgreSQL.** Añadir un valor a un `TYPE ... AS ENUM`
obliga a acrobacias en la migración. Usa `native_enum=False`, que genera
`VARCHAR` + `CHECK`.

**Todo `TIMESTAMPTZ`, nunca `TIMESTAMP`.** Una fecha de publicación del DOF sin
zona horaria es una fecha ambigua.

---

## 3. Campos transversales — no negociables

### Toda tabla

```
id            UUID PK DEFAULT gen_random_uuid()
created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
```

### Toda tabla con dato de negocio

```
data_origin   NOT NULL, CHECK IN ('OFFICIAL','PUBLIC','LICENSED','SYNTHETIC','HUMAN_VALIDATED')
source_id     UUID FK -> regulatory.legal_sources(id), NULL si no aplica
```

Los cinco valores son cerrados. **No inventes un sexto** (§9 del maestro).

### Toda tabla regulatoria (esquema `regulatory`)

```
published_at      DATE
valid_from        DATE NOT NULL
valid_to          DATE NULL        -- NULL = sigue vigente. NUNCA inventes una fecha.
source_url        TEXT NOT NULL
source_document   TEXT
content_hash      TEXT NOT NULL    -- sha256 del contenido normalizado
retrieved_at      TIMESTAMPTZ NOT NULL
```

Índice obligatorio para consultas por vigencia (§14 del maestro):

```sql
CREATE INDEX ... ON <tabla> (<clave_natural>, valid_from, valid_to);
```

### Toda tabla producto de una decisión de IA (esquema `intelligence`)

```
model_provider          TEXT
model_name              TEXT
prompt_version          TEXT
confidence              NUMERIC(5,4)   -- 0.0000 a 1.0000
requires_human_review   BOOLEAN NOT NULL DEFAULT false
```

### Toda tabla con dato sintético

```
synthetic_scenario_id   UUID FK -> operational.synthetic_scenarios(id)
seed                    BIGINT
```

---

## 4. Entidades

### `regulatory`
`legal_sources` · `legal_documents` · `legal_rules` · `tariff_fractions` ·
`nicos` · `regulatory_events`

### `operational`
`clients` · `suppliers` · `products` · `invoices` · `invoice_items` · `coves` ·
`pedimentos` · `pedimento_items` · `synthetic_scenarios`

### `intelligence`
`product_dnas` · `product_attributes` · `classification_decisions` ·
`classification_candidates` · `evidence_records` · `risk_findings` ·
`opportunity_findings` · `ground_truth_records`

### Detalles que no puedes improvisar

**`product_attributes`** — cada atributo lleva su propio estado y evidencia
(§16 del maestro):

```
value                 TEXT
status                CHECK IN ('OBSERVED','EXTRACTED','INFERRED','MISSING')
confidence            NUMERIC(5,4)
evidence_reference    UUID FK -> intelligence.evidence_records(id)
```

**`tariff_fractions`** — la fracción mexicana es de 8 dígitos y el NICO son 2
más, en tabla aparte. Guarda por separado `chapter` (2), `heading` (4),
`subheading` (6) y `fraction` (8) para poder consultar por nivel. El código va
como `VARCHAR`, **nunca** como entero: los ceros a la izquierda importan.

**`risk_findings`** — severidad `CHECK IN ('INFO','LOW','MEDIUM','HIGH','CRITICAL')`.

**`opportunity_findings`** — estado `CHECK IN ('POTENTIAL','VALIDATED','REJECTED')`.
`POTENTIAL` jamás se presenta como ahorro garantizado (§23 del maestro).

**`classification_decisions`** — debe poder responder las diez preguntas de §49
del maestro. Si tu modelo no las contesta, está incompleto.

**`evidence_records`** — es el contrato central. Toda decisión apunta aquí:
`source_ids`, documentos, hashes, versión del motor, versión del prompt.

---

## 5. Entregables

1. `database/models/*.py` — SQLAlchemy 2.0, `Mapped[]` / `mapped_column()`,
   type hints completos.
2. `schemas/*.py` — Pydantic v2, separando `Create` / `Read` / `Update`.
3. Una sola migración Alembic: `alembic revision --autogenerate -m "canonical model v0.1"`.
   **Revísala a mano**: el autogenerado se equivoca con esquemas e índices.
   El `downgrade()` tiene que funcionar de verdad.
4. `docs/ER_DIAGRAM.md` — diagrama Mermaid `erDiagram`.
5. `database/seeds/` — fixtures mínimas, todas marcadas `SYNTHETIC`.
6. `tests/` — que cada tabla tiene `data_origin`; que el CHECK rechaza un valor
   inválido; que `valid_to NULL` significa vigente; que un `Decimal` de dinero
   sobrevive el ida y vuelta a la base sin perder precisión.

### Definition of Done

`pytest` verde · `ruff check .` limpio · `mypy` limpio · `alembic upgrade head`
y `alembic downgrade base` funcionan contra una base **local tuya** ·
sin secretos · PR abierto contra `develop`.

---

## 6. Prohibido

- `CREATE TABLE` o `ALTER TABLE` a mano contra la base compartida.
- Aplicar la migración a `100.86.182.104:5433` antes de la aprobación de P1.
- Tocar el PostgreSQL nativo del puerto 5432.
- `FLOAT` para dinero, tasas o cantidades.
- Inventar un valor de `data_origin`.
- Inventar una fecha `valid_to` porque "seguramente ya venció".
- Implementar lógica de clasificación. Esto es sólo el modelo.

Si necesitas cambiar algo de este contrato, **detente** y marca
`ARCHITECTURE_DECISION_REQUIRED` en el PR. No lo decidas por tu cuenta.

---

## 7. Al terminar, reporta así (§46 del maestro)

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
