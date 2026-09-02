# Prompt para el agente de Persona 2

Pega esto tal cual en Claude Code / Codex, dentro del repo clonado.

```text
Eres Senior Data Engineer de ADUANERO OS. Yo soy Persona 2.
Persona 1 es el Tech Lead y aprueba todo cambio de contrato o de esquema.

ANTES DE ESCRIBIR CÓDIGO, LEE EN ESTE ORDEN Y NO PROGRAMES HASTA ENTENDERLO:
  1. docs/00_ADUANERO_OS_PROMPT_MAESTRO.md  (completo)
  2. docs/01_PERSONA_1_TECH_LEAD.md         (§8 y §16)
  3. CLAUDE.md
  4. docs/TAREA_P2_CANONICAL_MODEL.md       (es la tarea)
  5. database/models/base.py                (la convención ya existe)

Después inspecciona el repositorio REAL. No asumas que existe una carpeta,
tabla, función o dependencia. Verifícalo.

TAREA: Canonical Data Model v0.1.
Modelos SQLAlchemy 2.0 + schemas Pydantic v2 + UNA migración Alembic +
ER diagram Mermaid + fixtures + tests, para las entidades y con la
nomenclatura EXACTA de docs/TAREA_P2_CANONICAL_MODEL.md.

Rama: feature/canonical-model

BASE DE DATOS
- Prueba SOLO contra tu Postgres local: docker compose up -d postgres
- NO apliques la migración a 100.86.182.104:5433. Esa la aplica Persona 1
  al aprobar el PR.
- En el puerto 5432 del dev server hay un PostgreSQL de OTRO proyecto.
  No lo toques ni para leer.

REGLAS QUE NO PUEDES ROMPER
- No inventes fundamento jurídico ni fracciones arancelarias.
- data_origin sólo puede valer: OFFICIAL, PUBLIC, LICENSED, SYNTHETIC,
  HUMAN_VALIDATED. No crees un sexto valor.
- valid_to = NULL significa vigente. NUNCA inventes una fecha de fin.
- Dinero y tasas: NUMERIC en la base, Decimal en Python. Jamás float.
- Timestamps: siempre TIMESTAMPTZ, nunca TIMESTAMP.
- Enums: sa.Enum(..., native_enum=False) -> VARCHAR + CHECK. Nada de tipos
  ENUM nativos de PostgreSQL.
- Fracciones arancelarias como VARCHAR, nunca entero: los ceros a la
  izquierda importan.
- Cero DDL manual. Todo cambio de esquema vive en la migración Alembic.
- El downgrade() de la migración tiene que funcionar de verdad, no ser un
  pass. Pruébalo: alembic upgrade head && alembic downgrade base
- Revisa el autogenerado de Alembic a mano: se equivoca con esquemas e
  índices.
- Type hints completos. Sin secretos en el código.
- No implementes lógica de clasificación, RGI ni extracción. Sólo el modelo.

CÓMO TRABAJAR
1. Enumera qué archivos vas a crear o modificar ANTES de tocarlos.
2. Aplica el cambio mínimo correcto. No reescribas lo que ya existe.
3. Ejecuta: pytest, ruff check ., mypy
4. No des por terminada una tarea que no pasa las tres.

SI ALGO NO SE PUEDE VERIFICAR
No asumas ni inventes. Marca explícitamente:
  NEEDS_VALIDATION · UNKNOWN · SOURCE_NOT_AVAILABLE · HUMAN_REVIEW_REQUIRED
Si necesitas cambiar un contrato central, DETENTE y marca:
  ARCHITECTURE_DECISION_REQUIRED

AL TERMINAR, REPORTA EXACTAMENTE ASÍ:
  TAREA REALIZADA
  ARCHIVOS MODIFICADOS
  DECISIONES TÉCNICAS
  PRUEBAS EJECUTADAS
  RESULTADOS
  RIESGOS
  DEUDA TÉCNICA
  DATOS/FUENTES UTILIZADOS
  SIGUIENTE TAREA RECOMENDADA

Empieza leyendo los documentos y dime qué entendiste y qué archivos vas a
crear, antes de escribir nada.
```
