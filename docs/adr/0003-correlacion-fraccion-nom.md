# ADR 0003 — Correlación fracción → NOM (Anexo 2.4.1, no 2.2.1)

- **Fecha:** 2026-09-28
- **Estado:** aceptado (2026-09-30) — implementado (2026-10-04, Persona 1,
  commit `493f025`)
- **Decide:** Persona 1
- **Pregunta de:** Persona 2, verificando el pendiente que anota
  `core/shadow/types.py` (`required_nom_codes`) y `docs/ESTADO_DEL_PROYECTO.md`

## Contexto

`core/shadow` (el Pedimento Espejo) declara `required_nom_codes: tuple[str,
...] | None = None` para toda fracción, siempre — la correlación fracción →
NOM no está cargada. El propio código lo explica: «`None` dice "no tengo la
fuente para saberlo" y manda la partida a `unverifiable`». No es una
acusación: es un hueco declarado, y es el que se ve en pantalla (`docs/
DEMO_AJR.md`: «qué NOM exige la fracción (falta el Anexo 2.2.1)»).

**El número que todos citamos está mal.** El Anexo 2.2.1 del Acuerdo de la
SE es de **permisos previos**, no de NOM. La correlación fracción → NOM
está en el **Anexo 2.4.1** («Anexo de NOM's»), Capítulo 2.4 del mismo
Acuerdo. Verificado dos veces el 2026-09-28, de forma independiente:

1. Contra el propio texto del Acuerdo (`ACUERDO-REGLAS-SE-02ABRIL2026-
   BIBLIOTECA_20260520-20260520.pdf`, Biblioteca Jurídica de SNICE, 980
   páginas): el índice lista «Anexo 2.2.1 Clasificación y codificación de
   mercancías cuya importación y exportación está [sujeta a permiso
   previo]» y, por separado, «Anexo 2.4.1 Fracciones arancelarias… en las
   que se clasifican las mercancías sujetas al cumplimiento de las Normas
   Oficiales Mexicanas…».
2. Contra la página pública de normatividad de SNICE
   (`snice.gob.mx/cs/avi/snice/drrnas.noms.html`), que enlaza exactamente
   «Anexo 2.4.1… (Anexo de NOM's)» como la fuente de NOM por fracción.

`core/shadow/types.py:113` y los documentos de `docs/` que lo repetían ya
quedaron corregidos (PR #162, 2026-09-30), aparte de este ADR.

## Qué tiene el Anexo 2.4.1 (verificado contra el documento real, no supuesto)

No es una tabla plana de dos columnas. Tiene **5 numerales**, cada uno con
su propio alcance y regla de la SE que lo activa:

| Numeral | Qué cubre | Regla SE | Estructura |
|---|---|---|---|
| 1 | Importación, NOM al punto de entrada | 2.4.3 | Tabular: fracción/NICO → NOM |
| 2 | Importación, excluidas de la regla 2.4.11 | 2.4.3 | Tabular: fracción/NICO → NOM |
| 3 | Etiquetado e información comercial | 2.4.8 | **No tabular** — listas en romanos por capítulo de norma, mecanismo de cumplimiento distinto |
| 4 | Exportación | 2.4.9 | Tabular: fracción/NICO → NOM |
| 5 | NOM de emergencia | 2.4.3 | Vacío en la versión vigente |

Sobre los tres numerales tabulares (1, 2, 4): ~3 085 filas, ~2 530
fracciones distintas, al menos 83 NOM distintas. **917 filas traen una
acotación "Únicamente: …"** que limita la NOM a un subconjunto de la
fracción — a veces por producto (sólo tequila, dentro de una fracción de
licores en general), a veces por punto específico de la norma (sólo el
punto 9.2). Un mapeo fracción→NOM que ignore la acotación afirmaría una
NOM que no siempre aplica, y `MISSING_NOM` en `core/shadow/compare.py` es
una acusación contra el agente aduanal — no algo para equivocarse.

## Opciones consideradas

**(a) Tabla nueva `regulatory.fraction_nom_requirements`, por Alembic.**
Mismo patrón que `tariff_headings` (ADR 0002): entidad regulatoria propia,
`RegulatoryMixin` completo, vigencia por fila.

**(b) Meter la NOM como columna extra en `tariff_fractions`.** Descartada
por la misma razón que ADR 0002 descartó mezclar partidas ahí: una
fracción puede tener 0, 1 o varias NOM según el numeral y la acotación —
no es un escalar, y forzarlo perdería la acotación o exigiría una columna
JSON sin estructura ni CHECK.

**(c) Cargar sólo los numerales 1 y 2 (importación), dejar el 4
(exportación) para después.** Descartada: el corpus espejo son pedimentos
de importación, pero `required_nom_codes` no distingue por `trade_flow` en
el contrato — cargar parcial dejaría fracciones de exportación con `None`
indistinguible de «no cargado» y «no aplica», el mismo problema que el ADR
0002 evitó separando NULL de vacío.

## Decisión propuesta (29-sep)

**Opción (a).** Tabla nueva:

```
fraction_code    VARCHAR(8)  NOT NULL   -- 8 dígitos, como tariff_fractions.code
nico             VARCHAR(2)  NULL       -- si el numeral lo distingue por NICO
numeral          SMALLINT    NOT NULL   -- CHECK (numeral IN (1, 2, 4))
nom_code         VARCHAR(32) NOT NULL   -- "NOM-186-SSA1/SCFI-2013"
scope_note       TEXT        NULL       -- el texto de "Únicamente: …", tal cual
  UNIQUE (fraction_code, nico, numeral, nom_code, valid_from)
```

Más `RegulatoryMixin` completo (`valid_from`/`valid_to`, `data_origin`,
`source_id`, `source_url`, `content_hash`, `published_at`, `retrieved_at`)
y `DataOriginMixin` — misma garantía que toda tabla de `regulatory`: es la
misma norma, se publica en el DOF y cambia con reformas del Acuerdo.

**Alcance v1: numerales 1, 2 y 4** — los tres tabulares. El numeral 3
(etiquetado) queda fuera de esta tabla: su propia estructura (listas en
romanos, cumplimiento por Capítulo de norma) no encaja en filas
fracción→NOM, y forzarlo sería el mismo error que la opción (b) — PR
aparte si Persona 1 lo pide.

**`required_nom_codes` sólo se llena con filas SIN `scope_note`.** Una
fracción con únicamente filas acotadas devuelve `required_nom_codes = ()`
(vacío, no `None`: si algo se sabe, se dice) pero las acotadas se
reportan aparte — ese cableado es de `core/shadow`, no de esta carga; aquí
sólo se propone la regla para que el lado de lectura la aplique igual en
todos lados.

**Vigencia.** El anexo no trae un `valid_from` único: trae «Anexo
reformado, DOF 25 de noviembre de 2022» a nivel de anexo y notas de
reforma por numeral («Numeral reformado, DOF 28 de agosto de 2024»/«DOF 16
de agosto de 2022»). Propuesta: `valid_from` de cada fila = la fecha de
reforma más reciente citada en SU numeral (no la del anexo completo, por
la misma razón que ADR de Ley Aduanera separó vigencia por artículo de
vigencia del documento — un numeral sin tocar desde 2022 no hereda la
fecha de otro que se reformó en 2024). Si una fila no trae ninguna nota de
reforma propia ni heredada de su numeral, se marca `needs_validation` y no
se carga — mismo criterio que las 13 reglas del Transitorio Cuarto de
RGCE.

## Decisión de Persona 1 (2026-09-30)

**Las tres preguntas, respondidas. El ADR queda aceptado.**

**1. ¿Tabla nueva y alcance v1 (numerales 1, 2 y 4)?** Sí.

Es la opción correcta y por la misma razón que el ADR 0002: una fracción
con 0, 1 o varias NOM no es un escalar. Descartar la opción (c) porque
dejaría `None` indistinguible de «no aplica» es justo el criterio de esta
casa.

El numeral 3 queda fuera como deuda documentada, no como olvido: que
`required_nom_codes` siga en `None` para lo que sólo cubra ese numeral es
la respuesta honesta.

**2. ¿Sólo las filas sin `scope_note` alimentan `required_nom_codes`?**
Sí, y es la que más importa.

Si una NOM acotada a «únicamente tequila» alimentara el campo, el Espejo
emitiría `MISSING_NOM` contra un agente aduanal por una norma que a su
mercancía no le aplica. Eso es acusar sin fundamento, y es peor que
declarar el hueco.

Dos precisiones para que el cableado no se tuerza:

- Una fracción con **sólo** filas acotadas devuelve `()`, no `None`.
  Sabemos algo: que ninguna NOM aplica sin comprobar antes la acotación.
- Las acotadas se reportan aparte, van a `unverifiable` con su texto
  «Únicamente: …» íntegro. Que lo lea el clasificador y decida. El motor
  no interpreta «únicamente tequila» contra una ficha técnica.

**3. ¿«Fecha de reforma más reciente del numeral» como `valid_from`?** Sí.

Mismo criterio que la Ley Aduanera: la vigencia es del numeral, no del
anexo. Un numeral sin tocar desde 2022 no hereda la fecha de otro
reformado en 2024 — heredarla sería afirmar una vigencia que el DOF no
publicó. Marcar `needs_validation` y no cargar cuando no haya nota de
reforma propia ni heredada — no se inventa una fecha.

## Consecuencias (implementadas, commit `493f025`, 2026-10-04)

- **Persona 1** cargó el Anexo 2.4.1 (numerales 1, 2, 4) por el pipeline
  completo: `ingestion/se/anexo_2_4_1.py` (PARSED), `ingestion/se/load.py`
  (DATABASE), migración `fraction_nom_requirements` (reversible). **No
  toca** `tariff_fractions` ni ningún otro anexo.
- **456 filas cargadas** (no las ~3 085 crudas del documento — ya
  reconciliadas/deduplicadas contra fracción+numeral+NOM+vigencia), de las
  cuales **306 traen `scope_note`** («Únicamente: …» íntegro) y 150 no.
- Conectado a `core/shadow` (`database/repositories/tariff.py`,
  `apps/api/routers/pedimentos.py`): `required_nom_codes` ya no es
  `None` constante — aplica exactamente la regla de la pregunta 2 (sólo
  sin `scope_note` alimenta el campo; las acotadas van aparte).
- El numeral 3 (etiquetado) queda como deuda documentada, no resuelta:
  `required_nom_codes` sigue en `None` para lo que sólo esté cubierto por
  ese numeral.
- Corrección de número (2.2.1 → 2.4.1) ya aplicada en los 9 sitios del
  repo que lo citaban mal (PR #162, 2026-09-30).
