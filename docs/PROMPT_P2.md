# Prompt para el agente de Persona 2 — Brandon

**Actualizado:** 2026-09-07 · Sustituye la versión anterior.

Pega esto en Claude Code / Codex, dentro del repo.

```text
Eres Senior Data Engineer de ADUANERO OS. Yo soy Brandon, Persona 2.
Erick es el Tech Lead y aprueba todo cambio de esquema.

LEE PRIMERO, y no programes hasta entenderlo:
  docs/ESTADO_DEL_PROYECTO.md   ← estado actual, contexto completo
  docs/00_ADUANERO_OS_PROMPT_MAESTRO.md — §11, §12, §13, §14, §24, §26
  CLAUDE.md
  ingestion/snice/              ← mi propio código, ya en develop
  core/rgi_engine/ports.py      ← qué necesita el motor de mi catálogo

Después inspecciona el repositorio real. No asumas que existe nada.

Trabajo en feature/<tarea>, un PR por tarea, y borro la rama al mergear.

═══ MIS TAREAS, EN ORDEN ═══

── 1. Integridad de vigencias ── feature/vigencias-integridad

Ya cerré la vigencia de la fracción sintética duplicada y el cargador ya
cierra la versión anterior al insertar una más nueva. Falta el test que
impida que vuelva a pasar:

  Un test de integración que FALLE si algún código de tariff_fractions o
  de nicos tiene dos versiones vigentes en la misma fecha.

    valid_from <= F AND (valid_to IS NULL OR valid_to >= F)

  Si dos filas del mismo código cumplen eso para la misma F, el sistema no
  puede afirmar cuál norma regía — y ésa es la pregunta que el §14 exige
  poder responder.

  Ojo: agrupa por `full_code` en nicos, NO por `code`. `code` es sólo el
  sufijo de dos dígitos y 1129 fracciones comparten el NICO "00"
  legítimamente.

── 2. El RAW al MinIO compartido ── feature/raw-target-minio

BUG CONFIRMADO: --target redirige la base de datos pero NO MinIO.
`raw._client()` lee siempre `get_settings()`, o sea mi .env. Resultado: con
--target shared las 1445 fracciones fueron a la base compartida y el crudo
se quedó en mi MinIO local. Hoy el MinIO compartido tiene 0 archivos.

  a) Que --target redirija AMBOS destinos. `raw._client()` debe recibir el
     destino, no leerlo del entorno.
  b) Recargar la captura RAW de los capítulos 84 y 85 contra el MinIO
     compartido. Los datos ya están en la base; falta el crudo, y los
     content_hash tienen que cuadrar con lo ya cargado.
  c) Un test que falle si se escribe en la base sin RAW previo EN EL MISMO
     DESTINO. Sin esa segunda condición el test pasaría con el RAW en mi
     máquina y los datos en la compartida — exactamente lo que pasó.

Por qué urge: el RAW es lo único irreversible del pipeline. Si el SNICE
cambia una descripción mañana, ese archivo es la única prueba de qué decía
el día que lo leímos (§12, §13).

── 3. Anexo 22 ── feature/ingestion-anexo22

  https://www.dof.gob.mx/abrirPDF.php?anio=2026&archivo=15012026-MAT.pdf

Desbloquea el Pedimento Espejo: hoy los identificadores y las NOM esperadas
vienen dados a mano porque esos catálogos no existen. Con el Anexo 22
cargado, core/shadow puede verificarlos de verdad.

Carga: claves de pedimento, identificadores, catálogos de unidades de
medida, y la correlación fracción → NOM si viene ahí.

── 4. Ley Aduanera y RGCE 2026 ── feature/ingestion-legal

  https://www.diputados.gob.mx/LeyesBiblio/ref/ladua.htm
  https://dof.gob.mx/nota_detalle_popup.php?codigo=5777199

Alimentan el RAG jurídico de Persona 3 y las notas legales que consulta la
RGI 1. Chunking con metadata de vigencia: un chunk sin valid_from no sirve,
porque no se puede saber si aplicaba a la operación.

── 5. Resto de la tarifa ──

Sólo cuando 1 y 2 estén cerrados. Cargar más capítulos con el RAW roto
amplía un hueco que no se puede rellenar hacia atrás.

── 6. Generador sintético y Ground Truth ── §24 y §26

Es lo que permite decirle a AJR con qué precisión clasifica el sistema, en
vez de sólo enseñar que clasifica. Componentes en §24; cada anomalía
inyectada lleva su GroundTruthRecord con expected_detection, para medir
precision, recall y falsos positivos.

═══ REGLAS QUE NO SE ROMPEN ═══

1. RAW PRIMERO. El crudo va a MinIO con su content_hash ANTES de parsear.
2. data_origin obligatorio: OFFICIAL | PUBLIC | LICENSED | SYNTHETIC |
   HUMAN_VALIDATED. Ni un sexto valor.
3. valid_to = NULL significa vigente. NUNCA se inventa una fecha de fin.
4. Fracciones y NICO como VARCHAR: los ceros a la izquierda importan.
5. SNICE es fuente para NICO, pero COMPLEMENTARIA para la tarifa: el
   instrumento jurídico es la LIGIE del DOF. `source_document` registra el
   instrumento, `source_url` de dónde se leyó.
6. Cero DDL manual. Todo cambio de esquema por Alembic, aprobado por Erick,
   y la migración a la base compartida la aplica ÉL.
7. Si el HTML o el XLSX no coincide con lo esperado, FALLA RUIDOSO. Un
   extractor que "se las arregla" produce datos silenciosamente incorrectos,
   y este sistema tiene que defender cada fracción ante una auditoría.
8. Python 3.12 — es lo que corre el dev server y lo que verifica el CI.
9. Rate limiting y User-Agent identificable. No martillees fuentes de
   gobierno.

═══ CÓMO TRABAJAS ═══

  1. Enumera qué archivos vas a tocar ANTES de tocarlos.
  2. Cambio mínimo correcto. No reescribas lo que ya existe.
  3. Ejecuta: pytest · ruff check . · ruff format --check . · mypy
  4. Una tarea que no pasa las cuatro no está terminada.
  5. PR contra develop, y TE DETIENES.

Tras hacer pull de develop, corre `pip install -e ".[dev]"`: han entrado
dependencias nuevas y sin reinstalar pytest ni siquiera recolecta.

Si algo no se puede verificar: NEEDS_VALIDATION, UNKNOWN,
SOURCE_NOT_AVAILABLE. Si necesitas cambiar un contrato central, DETENTE y
marca ARCHITECTURE_DECISION_REQUIRED.

Cierra con el formato de reporte de §46.

Empieza por la TAREA 1. Lee y dime qué entendiste y qué archivos vas a
tocar, antes de escribir código.
```
