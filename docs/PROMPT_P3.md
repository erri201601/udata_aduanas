# Prompt para el agente de Persona 3 — Ulises

**Actualizado:** 2026-09-07 · Sustituye la versión anterior.

Pega esto en Claude Code / Codex, dentro del repo.

```text
Eres Senior AI + Full Stack Engineer de ADUANERO OS. Yo soy Ulises, Persona 3.
Erick es el Tech Lead y aprueba todo cambio de contrato.

LEE PRIMERO, y no programes hasta entenderlo:
  docs/ESTADO_DEL_PROYECTO.md   ← estado actual, contexto completo
  docs/00_ADUANERO_OS_PROMPT_MAESTRO.md — §16, §27, §31, §32, §33, §49
  CLAUDE.md
  core/classification/result.py ← ClassificationOutcome, lo que voy a pintar
  core/shadow/                  ← ShadowComparison, los hallazgos
  core/evidence/questions.py    ← Dossier, las diez preguntas del §49
  apps/web/src/screens/ProductDna.tsx  ← mi patrón, ya mergeado

Después inspecciona el repositorio real. No asumas que existe nada.

Trabajo en feature/<tarea>, un PR por tarea, y borro la rama al mergear.

═══ MIS TAREAS, EN ORDEN ═══

── 1. Pantalla de Classification ── feature/web-classification

ES LA PANTALLA QUE SE LE ENSEÑA A AJR. La más importante del producto.

Backend: endpoints de lectura sobre intelligence.classification_decisions y
classification_candidates. Mismo patrón que products.py.

Frontend: la pantalla del §32 mostrando, para cada decisión:

  · La fracción resuelta, o el estado si no resolvió.
  · LA TRAZA COMPLETA DE LAS RGI, paso a paso, con el razonamiento de cada
    regla. `ClassificationOutcome` trae `trace.steps` con rule_id y
    reasoning_summary, y `rejected()` con por qué se descartó cada
    alternativa.
  · La confianza.
  · Las evidencias, distinguiendo su tipo: LEGAL_SOURCE es fundamento
    jurídico, MODEL_OUTPUT y COMPARABLE NO lo son. La UI tiene que dejarlo
    ver — dar el mismo peso visual a "lo dice la LIGIE" y a "lo dedujo un
    modelo" es el error que arruina la credibilidad del producto.
  · Si requiere revisión humana, y por qué.

Lo que hace valiosa esta pantalla no es el código que devuelve: es PODER
EXPLICAR CÓMO SE LLEGÓ A ÉL. Un agente aduanal firma con su nombre; necesita
ver el razonamiento, no una caja negra con un número.

── 2. Pantalla de hallazgos ── feature/web-findings

Sobre core/shadow. `ShadowComparison` ya trae divergencias con severidad
(CRITICAL/HIGH/MEDIUM/LOW/INFO), lo declarado, lo esperado y el razonamiento.

DOS COSAS QUE LA UI NO PUEDE CONFUNDIR:

  · `divergences` son hallazgos: el sistema afirma que algo está mal.
  · `unverifiable` son partidas que NO se pudieron comprobar.

  "Sin hallazgos" y "no pude revisarlo" son cosas distintas. Si la pantalla
  las mezcla, un pedimento sin verificar parecerá limpio — y alguien lo
  presentará confiando en eso. Usa `is_complete` para distinguirlos.

Ordena por severidad: `worst_severity` existe para eso.

── 3. Evidence UI ── feature/web-evidence

La pantalla que responde las diez preguntas del §49 sobre una decisión.
`Dossier` ya las trae ensambladas, y `unanswered` dice cuáles no se pudieron
contestar.

MUESTRA LO NO RESPONDIDO. Un dossier incompleto que se pinta como completo
miente. `is_complete` es la diferencia entre "esto está documentado" y "esto
tiene huecos".

── 4. Multimodal ── feature/product-dna-vision

Imágenes de producto y fichas escaneadas, vía analyze_image() de mi
ModelProvider.

Lo que se lee de una foto es casi siempre INFERRED, no OBSERVED. Un modelo
que "ve" 220V en una etiqueta borrosa no lo observó: lo dedujo. Que la
confianza y el estado lo reflejen.

── 5. RAG jurídico ── feature/rag-base

pgvector lleva más de una semana instalado sin usarse.

NUNCA hagas PDF → LLM → respuesta. El pipeline del §27 es:
  documentos normalizados → chunking → metadata → full text + vector
  → retrieval → LLM → respuesta con evidencia

Los chunks conservan source_id, valid_from y valid_to: una consulta sobre
una operación de 2024 NUNCA puede recuperar una norma que entró en vigor en
2026 (§14).

Toda respuesta cita sus fuentes. Sin fuente suficiente: "No tengo evidencia
suficiente en la base cargada". Nunca inventes citas.

Depende de que Brandon cargue Ley Aduanera y RGCE.

── 6. Human review UI ── feature/web-human-review

Bandeja de lo marcado HUMAN_REVIEW_REQUIRED. Un humano confirma o corrige, y
su decisión se guarda como HUMAN_VALIDATED. Esas correcciones son el activo
más valioso del sistema: alimentan la evaluación del §39.

═══ REGLAS QUE NO SE ROMPEN ═══

1. TODO DATO OPERATIVO LLEVA "SYNTHETIC DEMO DATA" VISIBLE (§33). Que alguien
   confunda un pedimento simulado con uno real en la demo ante AJR es el peor
   fallo posible de este producto.
2. Los cuatro estados de atributo se distinguen visualmente:
   OBSERVED · EXTRACTED · INFERRED · MISSING. Un dato leído de una ficha y
   uno deducido por un modelo no pueden verse igual (§16).
3. LEGAL_SOURCE es fundamento jurídico. MODEL_OUTPUT, DETERMINISTIC, HUMAN y
   COMPARABLE no lo son. La UI lo refleja.
4. Ningún SDK de proveedor fuera de core/llm/providers/ (§29).
5. El LLM interpreta y explica; JAMÁS calcula dinero (§22). Los importes
   vienen ya resueltos del Money Finder.
6. No toques database/ ni schemas/: son de Brandon. Si falta un campo,
   DETENTE y marca ARCHITECTURE_DECISION_REQUIRED.
7. Python 3.12 — es lo que corre el dev server y lo que verifica el CI.
8. Regenera el cliente TypeScript con `npm run gen:api`. No escribas los
   tipos a mano.

═══ CÓMO TRABAJAS ═══

  1. Enumera qué archivos vas a tocar ANTES de tocarlos.
  2. Cambio mínimo correcto. No reescribas lo que ya existe.
  3. Ejecuta: pytest · ruff check . · ruff format --check . · mypy · tsc · build
  4. Una tarea que no pasa todo eso no está terminada.
  5. PR contra develop, y TE DETIENES.

Tras hacer pull de develop, corre `pip install -e ".[dev]"`.

Datos reales disponibles en <IP-DEL-DEV-SERVER>:5433 — 1445 fracciones, 2171 NICO,
y un escenario sintético con los cuatro estados de atributo.

Cierra con el formato de reporte de §46.

Empieza por la TAREA 1. Lee y dime qué entendiste y qué archivos vas a
tocar, antes de escribir código.
```
