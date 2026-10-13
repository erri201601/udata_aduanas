# Prompt para el agente de Persona 3 — Ulises

**Actualizado:** 2026-10-07 · Las tareas 1 y 2 están HECHAS; queda la 3.

> **Ulises, antes de nada (7-oct).** Mientras no estabas, Erick y Claude
> cerraron lo que te quedaba de las tareas 1 y 2. No las rehagas:
>
> - **Tarea 2** — tu #214, mergeado el 7-oct con un arreglo del script
>   (`DetachedInstanceError`; su test pasaba en vacío en el CI). Y el #220
>   unificó los dos contadores que tu ADR dejó anotados: tablero, métricas y
>   bandeja dicen hoy los tres 0.
> - **Tarea 1** — `feature/veredicto-en-classification`:
>   `GET /classifications/{id}/vigente` (`CasoVigente`), el formulario de la
>   bandeja extraído a `components/FormularioVeredicto.tsx` y usado en las
>   dos pantallas, y `components/DarVeredicto.tsx` en Classification con (a)
>   y (b) tal como están descritos abajo.
>
> Lo tuyo ahora es la **tarea 3, Knowledge Graph**. Revisa esos PRs cuando
> vuelvas: si algo no te convence, dilo.

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

── 0. POR QUÉ CAMBIA LA TAREA ──

La bandeja agrupada por pregunta ya no rinde. El 6-oct entraron tres cosas
en el motor (#201, #203) y la bandeja pasó de 30 tarjetas con pregunta a DOS,
que valen un caso cada una. Agrupar dos preguntas no le ahorra nada a nadie.

Lo que ahora necesita el clasificador es otra cosa: dar veredicto sobre lo que
el motor YA RESOLVIÓ. Hoy la precisión se mide en 72 partidas contra la
fracción declarada —que escribió el generador sintético— y sólo en 26 contra
su criterio. Cada veredicto suyo sobre un acierto del motor convierte un
número sintético en uno humano. Y en la consola no hay dónde hacerlo.

Tus cuatro dudas de esta mañana siguen valiendo: lo de las tres definiciones
de "pendiente" es la tarea 2, y no se pierde.

── 1. Veredicto desde la pantalla de Classification ── feature/veredicto-en-classification

QUÉ HAY HOY

  · POST /review/{decision_id} acepta un veredicto sobre CUALQUIER decisión,
    también las que el motor resolvió limpio y nunca estuvieron en la
    bandeja. El docstring lo dice: «es lo que hace falta para muestrear lo
    que la bandeja deja pasar». La API está; la pantalla no.
  · Classification enseña una decisión y su dictamen, pero cero llamadas a
    revisarDecision: se puede mirar, no actuar.
  · El formulario ya existe en HumanReview.tsx —tres salidas, fracción y NICO
    en campos separados, nota obligatoria en FALTA_INFORMACION—. Reutilízalo,
    no lo copies.

LAS DOS COSAS QUE ESTA PANTALLA TIENE QUE HACER BIEN, Y LAS DOS YA FALLARON

(a) EL VEREDICTO VA A LA DECISIÓN VIGENTE DE LA FICHA, NO A LA QUE SE PINTÓ.

    El 6-oct el clasificador dio un veredicto en PED_SIM_004-011 desde una
    pestaña abierta de antes: su veredicto quedó colgado de una decisión de
    la víspera, no de la que el motor tenía ese momento. Antes de enviar,
    pide la decisión vigente de esa ficha —la última por product_dna_id que
    no sea HUMAN_VALIDATED— y manda el veredicto a ésa.

    Si la vigente ya tiene veredicto, la API devuelve 409. Enséñalo como
    «ya dictaminada el <fecha>», no como error.

(b) AVISA CUANDO LA FRACCIÓN TECLEADA ES UNA QUE EL MOTOR CONSIDERÓ Y NO ELIGIÓ.

    Ese mismo veredicto llevaba 73121008 en «fracción correcta» mientras su
    propia nota explicaba que esa posición era INCOMPATIBLE con la mercancía.
    Estaba explicando qué hizo mal el motor y pegó el código de ahí. Un aviso
    lo habría parado:

      «El motor tuvo 73121008 como candidata y no la eligió. ¿Seguro?»

    Sácalo de `descartadas`, que cada paso de `rgi_trace` trae desde el
    6-oct-2026 (las trazas anteriores no lo traen: trátalo como lista vacía):

      "descartadas": [{"code": "73121008",
                       "motivo": "la ficha dice «6x36», que no es «constituidos por 7 alambres»",
                       "por": "RESPUESTA_FIRMADA"}]

    · `code` va al nivel en que se descartó —partida, subpartida o fracción—:
      compara por PREFIJO. Una fracción tecleada que empieza por una partida
      descartada también está descartada.
    · `por` es uno de NOTA_LEGAL, MATERIA, CONTRADICCION, RESPUESTA_FIRMADA.
      Con RESPUESTA_FIRMADA dilo: «una respuesta firmada dice que…».
    · Junta los `descartadas` de TODOS los pasos de la decisión vigente.
    · NO uses `candidate_codes` ni `classification_candidates.rejected_reason`:
      en una abstención todas las viables cuentan como «no elegidas» y el
      aviso saltaría en cada veredicto; y `rejected_reason` es el resumen del
      paso copiado, que en una abstención marca todo como rechazado.
    · Si el motor resolvió X y teclean otra que no está descartada, es un
      CORRIGE legítimo: basta con «el motor resolvió X».

    Medido en el corpus (181 productos): 298 descartes en 150 productos, y en
    ninguno la fracción elegida figura como descartada. En 004-011 el aviso
    habría saltado con el motivo de arriba.

    Es un aviso, no un bloqueo. La persona manda en el criterio.

── 2. Una sola definición de «pendiente» ── fix/una-definicion-de-pendiente

Lo que encontraste esta mañana sigue siendo un defecto real, aunque ya no haya
pantalla agrupada encima: la bandeja, el script de preguntas y el recálculo al
contestar usan tres conjuntos distintos.

La definición correcta, la de la bandeja:

  requires_human_review IS TRUE
  AND data_origin <> 'HUMAN_VALIDATED'
  AND es la última decisión de su product_dna_id

En database/repositories/preguntas.py como propusiste, y que la usen GET
/review, preguntas_pendientes.py y _casos_que_preguntaban (es mía, del #192,
y coge TODAS las pendientes en vez de la última). Y quita del script el filtro
que mira sólo el lado de la tarifa, como acordamos.

Ojo con el rendimiento: el 6-oct el tablero tardaba 54 s por esta misma
subconsulta sin índice. El #204 añadió (product_dna_id, created_at). Comprueba
con EXPLAIN que tu consulta común lo usa.

── 3. Knowledge Graph ── feature/knowledge-graph

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

── 4. Lo que NO es tuyo ahora ──

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

Empieza por la TAREA 1. Si ya tenías rama abierta para la bandeja por
pregunta, ciérrala. Lee y dime qué entendiste y qué archivos vas a tocar,
antes de escribir código.
```
