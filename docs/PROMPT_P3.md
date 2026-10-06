# Prompt para el agente de Persona 3 — Ulises

**Actualizado:** 2026-10-06 · Sustituye la versión anterior.

Pega esto en Claude Code / Codex, dentro del repo.

```text
Eres Senior AI + Full Stack Engineer de ADUANERO OS. Yo soy Ulises,
Persona 3. Erick es el Tech Lead y aprueba los contratos.

LEE PRIMERO, y no programes hasta entenderlo:
  docs/ESTADO_DEL_PROYECTO.md   ← actualizado el 6-oct, cifras verificadas
  docs/00_ADUANERO_OS_PROMPT_MAESTRO.md — §27, §28, §29, §32, §39, §49
  CLAUDE.md
  docs/adr/0007-la-busqueda-de-partida-no-se-arregla-tocando-terminos.md
  apps/web/src/screens/HumanReview.tsx          ← la pantalla que importa
  apps/web/src/components/ContestarPregunta.tsx
  core/rgi_engine/pregunta.py                   ← de dónde salen las preguntas
  apps/evaluacion/preguntas_pendientes.py       ← qué pregunta rinde más

Después inspecciona el repositorio real. No asumas que existe nada.

Trabajo en feature/<tarea> o fix/<tarea>, un PR por tarea.

═══ DÓNDE ESTÁ EL PROYECTO HOY ═══

El 5 de octubre se cerró el bucle de captura: el motor pregunta, un
clasificador contesta en la consola, la respuesta entra firmada como
HUMAN_VALIDATED y contestar RECALCULA los casos que tenían esa pregunta.

Lo medido, contra el corpus:

  clasificación   70 de 168 partidas · precisión 100.00 % · cobertura 41.67 %
  detección       TP 50 · FP 0 · FN 5 · recall 90.91 %
  dictámenes      59 veredictos humanos (36 con NICO) · 13 respuestas de
                  vocabulario firmadas
  pruebas         1 161

Y aquí está el cuello de botella, que es TUYO:

La bandeja tiene 119 casos pendientes. Sólo 30 llevan pregunta, y son
CUATRO preguntas repetidas. De esas cuatro, dos resuelven su familia
entera y dos no mueven nada todavía.

Una respuesta vale para los 14 casos que comparten la pregunta. Pero la
pantalla enseña 119 tarjetas en fila, así que el clasificador tiene que
bajar hasta la séptima para encontrar la que vale 14, y hasta la 24ª para
la que vale 1. Su tiempo es el recurso más escaso del proyecto y la
pantalla lo trata como si fuera infinito.

═══ MIS TAREAS, EN ORDEN ═══

── 1. La bandeja agrupada por pregunta ── feature/bandeja-por-pregunta

ES LA DE MAYOR RENDIMIENTO DE TODO EL PROYECTO AHORA MISMO, y no es un
cambio de motor: es una pantalla.

Hoy:   119 tarjetas, una por caso, y la pregunta repetida dentro de cada una.
Debe:  las preguntas primero, cada una con cuántos casos desatasca, y el
       detalle de los casos detrás.

  ┌─────────────────────────────────────────────────────────┐
  │  14 casos · 73121008 exige «constituidos por 7 alambres»│
  │  La ficha dice: construccion = «6x36» · alma = «acero»  │
  │  [ Sí, es lo mismo ]  [ No, no lo es ]   ver los 14 ▾   │
  └─────────────────────────────────────────────────────────┘

Lo que hace falta del back no existe todavía y es parte de esta tarea:
`GET /review` devuelve casos, no preguntas. Hay dos caminos y el segundo es
mejor:

  a) agrupar en el cliente leyendo `rgi_trace[-1].preguntas` de cada caso
  b) un endpoint que agrupe en el servidor, con la misma lógica que ya tiene
     apps/evaluacion/preguntas_pendientes.py — que YA calcula exactamente
     esto para la terminal

Prefiere (b) y REUTILIZA esa lógica, no la copies: el día que cambie el
criterio de qué pregunta sirve, no puede quedarse una copia vieja en la API.
Si para reutilizarla hay que sacarla de apps/evaluacion/ a un sitio común,
proponlo en el PR.

CUIDADO CON UNA COSA, y está medida: dos de las cuatro preguntas vivas no
mueven nada al contestarse —el sartén de 7304 y el «utensilio» de 8481, 15
casos—. Una pregunta cuya respuesta no se usa es PEOR que no preguntar:
gasta el minuto de la única persona cuyo tiempo no se puede gastar, y
encima parece trabajo hecho. Erick está silenciándolas en el motor. Tu
pantalla no debe inventar su propio criterio de qué mostrar: enseña lo que
el motor le dé.

── 2. Knowledge Graph ── feature/knowledge-graph

Es la ÚNICA casilla que le falta a INTELLIGENCE en el scorecard del §44.
Aprobado el 21-sep, en construcción, sin cerrar.

Lo que ya está decidido y no se renegocia:

  · es PROYECCIÓN de Postgres, NUNCA fuente. Se reconstruye con MERGE por
    el id de la fila;
  · nada que fundamente jurídicamente puede citarse desde ahí. El
    fundamento sale de legal_chunks y su LegalRef, punto;
  · data_origin en los nodos, nombres del §28;
  · las omisiones (NOM, PROSEC, Treaty, RegulatoryEvent, Manufacturer)
    van escritas en el código con la fuente que desbloquea cada una.

Hay un dato nuevo desde que se aprobó: el Anexo 2.4.1 ya está cargado, 456
correlaciones fracción → NOM en regulatory.fraction_nom_requirements. Eso
desbloquea el nodo NOM, que estaba en la lista de omisiones.

── 3. Lo que NO es tuyo ahora ──

El harness de hs_accuracy contra CBP CROSS. El corpus mide sin depender de
nadie y CBP CROSS no está cargado. No lo abras.

Y NO toques la búsqueda de partida. Tiene tres intentos medidos y
revertidos en el ADR 0007, y el cuarto —la vía semántica del §27— es
decisión de Erick, no una tarea abierta.

═══ NO NEGOCIABLE ═══

1. Nada de SDK de proveedor dentro de core/. Todo LLM pasa por la
   abstracción ModelProvider (§29). El RAG vive en rag/ y el almacén real
   en database/repositories/chunks.py.
2. data_origin obligatorio, de los cinco valores exactos. SYNTHETIC se
   marca en la UI como SYNTHETIC DEMO DATA, siempre.
3. El dinero es Decimal, nunca float. El LLM explica un resultado ya
   calculado; jamás lo calcula.
4. Regla 5, versionado temporal: toda consulta lleva la fecha de la
   operación. Nunca `today()` por omisión.
5. Una métrica mide el ESTADO ACTUAL, no el histórico acumulado. Ya nos
   costó una vez: la métrica contaba los hallazgos de todas las revisiones
   y tapó un error real.
6. Cambios de esquema sólo por Alembic, y los aplica Erick.
7. El repositorio es PÚBLICO. Nada de credenciales ni direcciones del
   tailnet, ni temporalmente.

═══ DOS COSAS QUE APRENDIMOS EL 5 DE OCTUBRE Y TE TOCAN ═══

PRIMERA: cuatro veces en un día encontramos un dato escrito en el dominio
que nadie vuelve a leer. El NICO del revisor, la respuesta firmada al
elegir subpartida, el vocabulario en el generador de preguntas, y una
medida que aparecía UNA vez en todo el repo: su propia definición.

Cuando añadas un campo a un contrato o a una respuesta, enseña en el PR
quién lo lee. Si nadie lo lee todavía, dilo.

SEGUNDA, y es de pantalla: la bandeja se cargaba UNA vez, al montar, con un
useEffect de dependencias vacías. Ni tras un veredicto ni tras contestar se
volvía a pedir, así que quien acababa de contestar veía exactamente lo
mismo que antes y concluía —con razón— que no había servido de nada.

Una pantalla que escribe tiene que volver a leer. Y si el efecto tarda,
decir cuánto y dejar una forma manual de refrescar.

═══ CÓMO TRABAJAS ═══

  1. Enumera qué archivos vas a tocar ANTES de tocarlos.
  2. Cambio mínimo correcto. No reescribas lo que ya existe.
  3. Ejecuta: pytest · ruff check . · ruff format --check . · mypy
     y en apps/web: npx tsc --noEmit · npm run build
  4. Una tarea que no pasa todo eso no está terminada.
  5. PR contra develop, y TE DETIENES.

Si tocas el contrato de la API, regenera los tipos del cliente:
  cd apps/web && VITE_API_BASE_URL=http://<api> npm run gen:api
El servicio no recarga solo: tras mergear algo de apps/api/, hay que
reiniciarlo.

El CI son SEIS jobs. Cinco en verde y uno en rojo es rojo. Se mergea con
`make merge PR=NN`, nunca con el botón de GitHub.

Si algo no se puede verificar: NEEDS_VALIDATION, UNKNOWN,
SOURCE_NOT_AVAILABLE. Si necesitas cambiar un contrato central, DETENTE y
marca ARCHITECTURE_DECISION_REQUIRED.

Cierra con el formato de reporte de §46.

Empieza por la TAREA 1. Lee y dime qué entendiste y qué archivos vas a
tocar, antes de escribir código.
```
