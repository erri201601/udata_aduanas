# ADR 0013 — El NICO en la salida de la clasificación

- **Fecha:** 2026-10-13
- **Estado:** aceptado e implementado (2026-10-13)
- **Decide:** Persona 1

## Contexto

El §19 pide que la clasificación entregue la fracción **y el NICO**, y el §39
pide medir la precisión del NICO. Comprobado el 13-oct contra la base
compartida: de las 105 decisiones vigentes con fracción, **0** traían
`nico_code`. El orquestador no lo calculaba.

## Medición antes de decidir

De esas 105 fracciones, 45 tienen **un único NICO** vigente en la LIGIE y 60
tienen varios. Contra los veredictos de César, en las de un único NICO: **14 de
14** coinciden con el que firmó (las otras 5 no traían NICO).

## Decisión

**Una regla, la que no elige:** si la fracción defendible tiene un único NICO
vigente en la fecha de la operación, ése es el NICO (`core.classification.nico_de`).

- Con **varios**, no se elige. El NICO distingue por materia, uso o
  presentación, y ninguna regla medida lo hace todavía. `nico_reason` lo dice
  y va al razonamiento persistido.
- **Sin NICO cargados** o fracción no vigente: no se pone «00» por costumbre.
- **Sin fracción defendible no hay NICO**, ni se consulta.
- No cambia `requires_human_review`, ni el estado, ni la bandeja: es una regla
  sola y se mide sola («una regla por vez»).

Misma disciplina que la RGI 6 y que el Espejo (`_nico_esperado`, 21-sep):
resolver sólo cuando queda uno.

## Medición (§39)

`apps/evaluacion/clasificacion_39.py` añade la sección NICO, **sólo donde la
fracción acertó** (medir el NICO de una fracción equivocada mezclaría dos
errores). Aplica `nico_de` a la fracción propuesta —es determinista, así que
no hace falta reclasificar el corpus— y lo compara con el NICO del dictamen o,
si no hay, con el declarado (las partidas con `WRONG_NICO` ya están excluidas).

Resultado del 13-oct: **40 de 40** (±4,38 al 95 %), y se abstiene en 58 de 98
porque la fracción tiene varios NICO. La precisión de fracción no cambia
(98/98).

## Lo siguiente

Bajar la abstención exige una regla para elegir entre varios NICO. Sólo con
medición antes y después, y contra los 25 casos en que César firmó un NICO en
fracciones de varios.
