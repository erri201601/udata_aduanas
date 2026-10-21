# ADR 0020 — EBTI: las BTI de la Unión Europea como casos comparables

- **Fecha:** 2026-10-21
- **Estado:** aceptado (2026-10-21, por delegación de Persona 1)
- **Decide:** Persona 1, que delega lo técnico; queda escrito aquí.
- **Sigue a:** ADR 0019 (CBP CROSS). Usa la misma tabla y la misma regla: caso
  comparable, nunca fundamento.

## Contexto

El maestro (§11) pide EBTI como «casos comparables internacionales» y avisa:
«No convertir CN/TARIC directamente a clasificación mexicana». En el
scorecard (§44), «EBTI» estaba en cero.

Qué ofrece la Comisión, comprobado el 21-oct:

- **Publicaciones diarias** (`daily_publications.jsp`): un ZIP por día con un
  CSV de las BTI emitidas o invalidadas ese día. La página lista **el último
  mes** (30 archivos). Para descargarlas hay que seguir una redirección y
  guardar la cookie.
- **«Download All BTIs» y la búsqueda** dependen del JavaScript de la página
  (envíos de formulario con sesión). Replicarlo sería frágil: no se usa.

El CSV es oficial y estructurado: referencia, país, vigencia, código NC, la
**justificación de la clasificación**, estado (`VALID` o `INVALID`, con un
código de motivo), la descripción de la mercancía y palabras clave. Viene en el
idioma del país emisor.

## Decisión

1. **Misma tabla, `comparable_rulings`**, con `authority = EBTI` y
   `collection` = país emisor. Mismo aviso en pantalla, ya generalizado:
   «Casos de otras aduanas (EE. UU., Unión Europea), no fundamento jurídico en
   México…».
2. **Se cargan las 30 diarias que hay** (unas 5 000 BTI, de todos los
   capítulos) y no sólo las del corpus. Son pocas, cuestan poco y sirven para
   cualquier producto que se clasifique después. Un **timer diario** suma las
   siguientes, de modo que el corpus crece desde hoy.
3. **Vigencia propia:** `valid_from` y `valid_to` son los de la BTI, que
   normalmente dura tres años. Una invalidación posterior llega en otra diaria;
   se procesan de la más antigua a la más reciente y el estado se actualiza.
4. **El motivo de invalidación es un código numérico** (64, 65…) cuyo
   catálogo no viene en el archivo. Se guarda tal cual en `categories`, sin
   inventarle un significado.
5. **Texto:** descripción y justificación, verbatim, bajo etiquetas nuestras.
   El extracto que se muestra es la justificación literal, en su idioma. El
   vector (multilingüe) usa la descripción y la justificación, así que una
   ficha en español se compara con una BTI en francés o en alemán.
6. **Sólo HS6**, como en CBP. El código NC se guarda tal cual y no se traduce.
7. **RAW por diaria**, con el hash en la clave
   (`ebti/diarias/EBTI_AAAAMMDD_hhmmss_{sha16}.zip`). La URL de cada BTI es la
   de detalle `showHeader=false`, la única variante que respondió 200 sin
   sesión.

## Resultado esperado de la carga

Las 30 diarias se leyeron sin errores: 5 004 filas, 4 990 BTI distintas (14
reaparecen para cambiar de estado) y 848 invalidadas. Caen en partidas del
corpus 64: 6911 (5), 6912 (11), 7312 (4), 7321 (4), 7323 (27), 7324 (2) y 7615
(11).

## Límites

- El histórico anterior al último mes no está. Crece desde hoy.
- La justificación está en el idioma del país emisor y no se traduce. Traducir
  con un LLM haría que un texto ajeno sonara a criterio propio.
