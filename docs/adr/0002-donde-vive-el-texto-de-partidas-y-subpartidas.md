# ADR 0002 — Dónde vive el texto de partidas y subpartidas

- **Fecha:** 2026-09-22
- **Estado:** aceptado
- **Decide:** Persona 1
- **Pregunta de:** Persona 3 (`ARCHITECTURE_DECISION_REQUIRED`, 22-sep)

## Contexto

El motor no encuentra fracciones candidatas para mercancías que un clasificador
humano ubica sin esfuerzo. Es la causa de los 6 falsos negativos de fracción de
la métrica del §26 — el único hueco de detección que es del motor y no de código
que falte.

La razón, comprobada contra la base el 22-sep: **la descripción de una fracción
no se sostiene sola.** Para la partida 7323:

```
73231001  Lana de hierro o acero; esponjas, estropajos, guantes y artículos…
73239103  De fundición, sin esmaltar.
73239204  De fundición, esmaltados.
73239305  De acero inoxidable.
73239999  Los demás.
```

`De acero inoxidable.` no dice de qué. El sujeto vive en el texto de la partida
—«Artículos de uso doméstico, higiene o tocador, y sus partes, de fundición,
hierro o acero»— y **ese texto no está en ninguna columna de la base**.

Cuánto pesa, medido sobre las 8 136 fracciones:

| |  |
|---|---|
| descripciones de menos de 25 caracteres | **3 683 (45 %)** |
| descripciones que empiezan por «Los demás» | **2 104 (26 %)** |
| filas de 4 o 6 dígitos en `tariff_fractions` | 0 |

Así que «SARTEN DE ACERO INOXIDABLE PARA COCINA» no puede casar con
`De acero inoxidable.` por ningún método de búsqueda: el término que decide
—sartén, artículo de uso doméstico— no está en el texto que se compara.

## Opciones consideradas

Persona 3 planteó tres. Se descartan dos.

**(b) Reutilizar `legal_rules.heading_text` — descartada.** El nombre engaña:
`heading_text` es el título de la *regla* (el encabezado de un artículo), no el
texto de una partida arancelaria. Está en `NULL` en todas las filas, nunca se ha
poblado. Meter ahí la nomenclatura pondría el catálogo detrás del RAG, y la
búsqueda de candidatas es determinista, no semántica.

**(c) Sólo en `legal_chunks` — insuficiente por sí sola.** El RAG le da texto al
LLM; la búsqueda de candidatas la hace `TariffCatalogRepository` contra el
catálogo. Cargarlo sólo ahí dejaría el hueco igual. **Sí se hará, pero después
y como complemento** (ver Consecuencias).

**Y una cuarta que nadie propuso y hay que decir en voz alta: meter filas de 4 y
6 dígitos en `tariff_fractions`. Prohibida.** `code` es `VARCHAR(8)` y
`subheading` es `NOT NULL`: una fila de 4 dígitos tendría que falsificar la
subpartida. Peor, `TariffCatalogRepository` busca por `description ILIKE`, así
que el motor podría devolver `8471` como candidata y clasificar a algo que **no
es una fracción**. Eso es inventar fundamento arancelario y viola la regla 2.
Persona 3 detuvo la carga por esto y tenía razón.

## Decisión

**Opción (a): tabla nueva `regulatory.tariff_headings`, por Alembic.**

Una tabla cuya invariante es «nodo de la nomenclatura por encima de la
fracción», separada de la tabla cuya invariante es «fracción de 8 dígitos».

```
code         VARCHAR(6)  NOT NULL   -- 4 o 6 dígitos
level        SMALLINT    NOT NULL   -- CHECK (level IN (4, 6))
chapter      VARCHAR(2)  NOT NULL
description  TEXT        NOT NULL
  CHECK (length(code) = level)      -- un código de 8 no entra aquí
  UNIQUE (code, valid_from)
```

Más `RegulatoryMixin`: `valid_from`/`valid_to`, `data_origin`, `source_id`,
`source_url`, `content_hash`, `published_at`, `retrieved_at`. Las mismas
garantías que la tarifa, porque es la misma tarifa: se publica en el DOF y
cambia con ella.

### Las dos reglas que la hacen segura

1. **Una partida NUNCA es un resultado de clasificación.** `classify_product`
   sigue devolviendo exclusivamente códigos de `tariff_fractions`. El texto de
   4 y 6 dígitos sirve para **acotar candidatas** y para **citar la RGI 1**,
   jamás para responder. La separación de tablas es lo que lo garantiza por
   construcción y no por disciplina.
2. **La descripción con la que se compara es la de la jerarquía completa**, como
   se lee la LIGIE: texto de partida › texto de subpartida › descripción de la
   fracción. `De acero inoxidable.` pasa a compararse como «Artículos de uso
   doméstico… de fundición, hierro o acero › De acero inoxidable.». Eso es lo
   que cierra los 6 FN, no la tabla por sí sola.

## Consecuencias

- **Persona 2** carga el texto de partidas y subpartidas de la LIGIE 2026 por el
  pipeline completo (`SOURCE → RAW → PARSED → NORMALIZED → VALIDATED → DATABASE`,
  regla 7), con `data_origin = OFFICIAL`, `source_id` y `content_hash`. Migración
  Alembic reversible. **No toca `tariff_fractions`.**
- **Persona 1** cambia `TariffCatalogRepository` para que la búsqueda compare
  contra la descripción de la jerarquía completa, y vuelve a medir el §26. Es la
  tarea que debe mover los 6 FN de fracción.
- **Después, como complemento:** publicar esos textos como `legal_chunks` de la
  LIGIE, para que el expediente pueda citar la RGI 1 contra el texto real de la
  partida. El #109 ya dejó a la LIGIE dentro de `FUNDAMENTAN_CLASIFICACION`, así
  que entra sin más cambios. Esto es la opción (c), que no competía con la (a):
  venía detrás.
- **Nada de esto entra antes de la demo.** Toca el catálogo y la clasificación,
  que es justo lo que se enseña.

## Addendum 23-sep: hay una segunda causa, y es independiente

La primera corrida real de `hs_accuracy` (Persona 3, #125) dio **0 de 10**, y
al seguirlo hasta el final aparece un defecto que **el texto de partidas no
arregla**: la selección de candidatas.

`_coincide(terms)` es un **OR**. Cualquier partida que toque UNO de los seis
términos entra como candidata. Y `_coincidencias` —cuántos términos casa cada
partida— se calcula ya, pero **sólo se usa para ordenar**, nunca para filtrar.
La RGI 3 c) elige «la última en orden numérico», que no mira ese orden, así que
el ruido acaba ganando.

Medido el 23-sep contra el catálogo, para un estropajo de acero inoxidable:

| candidatas que casan | cuántas | la RGI 3 c) elegiría |
|---|---|---|
| ≥ 1 término | 60 | 9605 |
| ≥ 2 términos | 14 | 8481 |
| **≥ 3 términos** | **1** | **7323** ← la correcta |

La 7323 es «Lana de hierro o acero; esponjas, estropajos, guantes y artículos
similares». Con el filtro adecuado, el motor la encuentra sola.

**Pero un umbral fijo no sirve**: el mismo ≥3 deja una vajilla de porcelana en
**cero** candidatas, y a un sartén y a una olla no los arregla. Lo que el dato
sí establece es que `coincidencias` como FILTRO es mucho más potente que como
criterio de orden, y que el diseño correcto es quedarse con el mejor nivel que
exista para cada mercancía, no con un número escrito a mano.

Dos defectos menores del mismo camino, medidos a la vez:

- **`MIN_LONGITUD_TERMINO = 5` tira «OLLA».** La palabra más discriminante de
  una olla a presión se pierde por tener cuatro letras.
- **No hay palabras vacías.** «PRESENTACION», «CAPACIDAD», «DIAMETRO» y
  «CUERPO» entran como términos de búsqueda y ocupan cupo de los seis.
  «PRESENTACION» trae quesos (0406) y fósforos (3606).

**Por qué no se arregla todavía:** cualquier umbral que se afine hoy se afina
contra descripciones que están a punto de cambiar —cuando se cargue el texto de
partidas, «SARTEN» dejará de competir contra `De acero inoxidable.` y competirá
contra «Artículos de uso doméstico… de fundición, hierro o acero»—. El orden
correcto es cargar primero, volver a medir, y ajustar la selección de
candidatas contra el catálogo definitivo.

## Lo que esta decisión no resuelve

Que el motor encuentre la candidata correcta no implica que la resuelva: las 6
partidas de fracción salen hoy `HUMAN_REVIEW_REQUIRED`, y eso es el
comportamiento correcto cuando no hay con qué sostener una clasificación. Puede
que al tener el texto de la partida sigan pidiendo revisión humana, y seguiría
estando bien. Lo que cambia es que hoy fallan por no tener qué leer.
