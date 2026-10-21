# ADR 0019 — CBP CROSS: casos comparables, nunca fundamento

- **Fecha:** 2026-10-20
- **Estado:** aceptado (2026-10-20, por delegación de Persona 1)
- **Decide:** Persona 1, que delega lo técnico; queda escrito aquí.

## Contexto

El maestro (§11) pide CBP CROSS como «casos internacionales comparables:
producto → HS6 → razonamiento», con una condición: «No convertir
automáticamente HTS10 a TIGIE». El §19 pone «comparable cases» entre las
entradas del Classification Engine. En el scorecard (§44), «CBP» estaba en cero.

`rulings.cbp.gov` tiene una API JSON pública:

- **`/api/search`** busca por palabra. «7615» encuentra resultados, pero
  «7615.10» no, porque los puntos parten el término.
- **`/api/ruling/{n}`** devuelve la resolución entera: texto, fecha, asunto,
  códigos HTSUS y qué la revoca o modifica.

Las resoluciones son obra del gobierno de EE. UU., de dominio público.

## Decisión

1. **Tabla propia `regulatory.comparable_rulings`, separada de
   `legal_chunks`.** Una resolución de CBP dice cómo clasificó EE. UU. en SU
   arancel. Sirve para ver qué se consideró y cómo se razonó, pero nunca
   fundamenta una fracción mexicana. Separarla impide que el RAG jurídico (y
   el Copilot) la citen como ley. Está pensada para recibir también EBTI
   (`authority`).
2. **No se convierte HTS a TIGIE.** `tariff_codes` guarda los códigos tal como
   los escribe CBP. Sólo `hs6_codes` (los seis dígitos del Sistema
   Armonizado, comunes a los dos países) se compara con México. Los capítulos
   98 y 99 son disposiciones nacionales de EE. UU. y no dan HS6.
3. **`data_origin = PUBLIC`.** Es pública, pero no oficial en México.
   `valid_from` es la fecha de la resolución.
4. **Las revocadas se conservan, marcadas** (`is_revoked`, `revoked_by`): saber
   que CBP abandonó un criterio también informa. Al recargar se actualiza el
   estado; el texto de una resolución emitida no cambia.
5. **RAW por resolución**, con clave direccionada por contenido
   (`cbp_cross/{colección}/{número}_{sha16}.json`). Se guarda la URL pública
   (`rulings.cbp.gov/ruling/{n}`), no la de descarga, que es un enlace firmado
   de S3 que caduca a los 15 minutos.
6. **Alcance: las partidas del corpus**
   (`python -m ingestion.cbp_cross.cli --target local --desde-corpus`). Se
   busca por partida (4 dígitos), se recorren todas las páginas y se queda lo
   que cita un código de esa partida. Al 20-oct: unas 220 resoluciones de
   ocho partidas, de 1988 a 2026. No se descarga todo CROSS: lo que no se
   consulta no se carga (lección del FIX).
7. **Servicio público, sin martillarlo:** 0.4 s entre peticiones.

## Límites

- **La búsqueda de CROSS es por texto.** Una resolución que cita la fracción
  sólo en un formato que la búsqueda no tokeniza puede quedar fuera. Lo que
  se carga es «lo que CROSS devuelve al buscar la partida», no «todas las
  resoluciones de la partida».
- **Nada consume todavía esta tabla.** Mostrar «qué decidió CBP para esta
  subpartida» junto a una clasificación es el siguiente paso, en su propio
  PR. Ahí debe decir, con todas sus letras, que no es fundamento.

## Actualización 2026-10-20 (misma tarde)

- **El detalle no trae las revocaciones.** `/api/ruling/{n}` devuelve
  `revokedBy: null` aunque la resolución esté revocada; el resumen de
  `/api/search` sí lo dice (HQ 087732, 6912.00.41, revocada por 950390). La
  primera carga dejó así las 868 como vigentes. Ahora el RAW guarda el detalle,
  el resumen y la combinación (`cross.combinar`): las relaciones vienen del
  resumen cuando el detalle no las trae. Al recargar, el cargador sólo
  actualiza el estado de las filas existentes.
- **Alcance real: 868 resoluciones de 14 partidas, no 220 de 8.**
  `--desde-corpus` toma también las partidas de las decisiones de
  clasificación, y entre ellas hay decisiones sintéticas de pruebas (8471,
  8479, 8544, 7220, 7304, 7306). Son resoluciones reales y `PUBLIC`, así que se
  quedan. Que el alcance salga de las decisiones es deliberado: es lo que el
  sistema clasifica.

## Actualización 2026-10-20 — en la consola

`GET /classifications/{id}/comparables` toma la HS6 de la fracción de la
decisión y devuelve hasta 5 resoluciones (`?limite=` hasta 25): primero las
vigentes y después las más recientes, con el total. Cada una lleva un
**extracto literal**: la frase en que CBP fija la subpartida, o el HOLDING, o
el inicio de los hechos. Nunca es un resumen generado. La respuesta trae
siempre el aviso «no fundamento», y la pantalla de Classification lo muestra en
la sección «Casos comparables», después de «En qué se sostiene» y separada de
ella.

**Límite visto en el recorrido.** La HS6 agrupa mercancías que no se parecen:
para una olla de presión (7615.10) salen una casa de hámster y unos braseros
de aluminio. El orden es por vigencia y fecha, no por parecido. Ordenar por
parecido con la ficha exige comparar textos en dos idiomas (fichas en español,
resoluciones en inglés); es la siguiente mejora.

## Actualización 2026-10-21 — ordenados por parecido con la ficha

Se añadió `comparable_rulings.embedding`, con el mismo proveedor y dimensión
que el RAG y un modelo multilingüe. Se vectoriza el **asunto más el extracto
literal**, no el texto entero: membretes y cortesías sólo meten ruido. El
backfill es idempotente: `python -m ingestion.cbp_cross.vectores --target local`.

La consulta vectoriza el nombre y la descripción de la ficha (en español) y
ordena las resoluciones de la HS6 por coseno: primero las vigentes y, sin
vector, al final. El vector de la ficha se guarda en caché en el proceso. Si no
hay proveedor, o la decisión no tiene ficha, se ordena por fecha y la
respuesta lo dice (`orden`, `motivo_orden`), igual que el RAG degrada a término
y lo declara.

Medido a mano antes de construirlo, con el proveedor real:

- **Olla de presión (7615.10):** suben «Aluminum cookware (Circulon)» y
  «aluminum ware cook kit»; las persianas quedan al final.
- **Sartén (7323.93):** el comedero de pájaros queda al final.

Es una mejora moderada pero clara. El número de parecido viaja en la API y no
se muestra en la pantalla, porque un 0.33 no le dice nada a un clasificador.
