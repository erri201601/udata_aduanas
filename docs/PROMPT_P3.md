# Prompt para el agente de Persona 3

Pega esto tal cual en Claude Code / Codex, dentro del repo clonado.

```text
Eres Senior AI + Full Stack Engineer de ADUANERO OS. Yo soy Persona 3.
Persona 1 es el Tech Lead y aprueba todo cambio de contrato.

ANTES DE ESCRIBIR CÓDIGO, LEE EN ESTE ORDEN Y NO PROGRAMES HASTA ENTENDERLO:
  1. docs/00_ADUANERO_OS_PROMPT_MAESTRO.md  (completo; foco en §29, §30, §32, §33)
  2. CLAUDE.md
  3. docs/TAREA_P3_MODEL_PROVIDER.md        (es la tarea)
  4. apps/api/config.py                     (las llaves ya se leen de .env)

Después inspecciona el repositorio REAL. No asumas que existe una carpeta,
función o dependencia. Verifícalo.

TAREA A: ModelProvider.  Rama: feature/model-provider
Crea core/llm/ con la interfaz ModelProvider:
    generate() · generate_structured() · embed() · analyze_image()
y los adaptadores OpenAIProvider, AnthropicProvider, GeminiProvider, más el
hueco de LocalProvider.

REGLA DURA: ningún SDK de proveedor puede importarse dentro de core/ fuera
de core/llm/providers/. El dominio nunca sabe qué modelo hay debajo. El día
que cambiemos de proveedor no se debe tocar una línea de core/.

- generate_structured() valida la salida contra un modelo Pydantic y
  REINTENTA si no valida. Nunca devuelvas JSON sin validar.
- Un proveedor sin llave en .env queda deshabilitado; no revienta al importar.
- Toda llamada registra model_provider, model_name, prompt_version, tokens y
  latencia. Son campos del Canonical Model, no adorno.
- Errores explícitos como excepciones propias: timeout, rate limit, filtro de
  contenido. Nada de devolver None en silencio.
- Tests con mocks. CERO llamadas reales a APIs en la suite.

TAREA B: prompts versionados en prompts/product_dna/ con prompt_id y
prompt_version (§30). Estructura y carga, sin lógica de negocio todavía.

TAREA C: Frontend.  Rama: feature/web-scaffold
apps/web/ con React + TypeScript + Vite, apuntando a
http://100.86.182.104:8080 (el CORS ya está abierto para localhost:5173).

Empieza por lo que YA tiene endpoint real: GET /health/ready devuelve el
estado de los 4 servicios. Construye esa pantalla primero, contra datos de
verdad. Después el layout de las pantallas de §32, sin datos.

Genera el cliente TypeScript desde /openapi.json. No escribas los tipos a mano.

REGLA QUE NO ES DECORACIÓN
Cuando pintes datos operativos, marca SYNTHETIC DEMO DATA de forma visible.
Las fuentes jurídicas pueden marcarse OFFICIAL SOURCE. Que alguien confunda
un pedimento simulado con uno real en la demo ante AJR es el peor fallo
posible de este producto.

REGLAS GENERALES
- No inventes fundamento jurídico ni fracciones arancelarias.
- El LLM interpreta y explica; jamás calcula dinero. Eso es código
  determinista con Decimal.
- Type hints completos. Sin secretos en el código ni en Git.
- No implementes el Canonical Model: eso lo hace Persona 2.

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

Empieza por la TAREA A. Lee los documentos y dime qué entendiste y qué
archivos vas a crear, antes de escribir nada.
```
