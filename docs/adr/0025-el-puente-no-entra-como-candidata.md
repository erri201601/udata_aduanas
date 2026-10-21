# ADR 0025 — El puente de vocabulario tampoco entra como candidata

- **Fecha:** 2026-10-21
- **Estado:** aceptado (2026-10-21, por delegación de Persona 1). Se midió y se
  descartó; el código del intento no entró.
- **Decide:** Persona 1, que delega lo técnico; queda escrito aquí.
- **Sigue a:** ADR 0007 y PR #188, que dejaron escrito «buscar con el puente,
  sí; ganar con él, no».

## Contexto

El puente de vocabulario (`nomenclature_synonyms`, `EQUIVALE`) une una palabra
comercial con un texto de la tarifa. Hoy no cambia ninguna clasificación: cae
siempre fuera del tope de seis términos. En #188 se probó dejarlo pasar como
un término más, y costó 17 fallos, porque además de encontrar partidas les
sumaba un punto de cobertura y las hacía ganar.

Quedaba por probar la otra mitad: que el puente **encontrara** sin **ganar**.

## Lo que se probó

El puente viaja aparte de los términos de la ficha, de `clasificar_borrador`
al catálogo (`ClassificationContext.puentes`). En `headings`:

- la cobertura cuenta **sólo** los términos de la ficha, igual que hoy;
- una partida que casa un puente entra en candidatas si queda a un punto de la
  mejor cobertura. Sin ese margen, el puente no añadiría nada, porque las
  partidas con la mejor cobertura ya entran por sí mismas.

## Medición

Se reclasificaron las 188 partidas con el código del intento, dentro de una
transacción revertida, con la medición del §39
(`clasificacion_39 --reclasificar`):

```
                       contestó  acertó  falló  precisión  cobertura
mismo código, sin puente 103/164     99      4    96.12 %    62.80 %
puente como candidata     77/164     73      4    94.81 %    46.95 %
```

La fila de control es el mismo código con la lista de puentes vacía: así la
diferencia es del puente y no de otra parte del cambio. La línea base de
`develop`, medida antes con un script suelto, dio 104 y 100 (63.41 %). Ese caso
de diferencia no está aislado.

Los 4 «fallos» son los mismos en las dos filas: cables cuya declaración
sintética dice `73121099` y el motor `73121005`. Es la familia que el
clasificador resolvió el 6-oct a favor del motor, sin dictamen propio en estos
productos.

**Ningún acierto nuevo y 27 contestaciones menos.**

## Por qué

Se probó cada puente por separado: cuántas fichas reciben al menos una
candidata nueva sólo por él. Los que más añaden:

```
de hierro o acero                          90
mesa                                       30
oleoductos                                 29
gasoductos · recubrimiento                 15 cada uno
articulos de uso domestico y sus partes    15
sin galvanizar                             12
```

Son textos que la tarifa repite en capítulos enteros. «De hierro o acero»
aparece en casi todo el 72 y el 73. Un puente así no señala una partida:
abre medio capítulo. Con varias candidatas más, el motor ya no puede elegir
y se abstiene. Hace bien en abstenerse, pero contesta menos.

Por eso no hubo ningún error nuevo. El puente no engaña al motor; lo deja sin
poder decidir.

## Decisión

No entra. El ADR 0007 ya lo escribió: una mejora que convierte respuestas en
abstenciones sin ganar ningún acierto no es una mejora.

Lo que sí entra es la herramienta para medir el siguiente intento:
`python -m apps.evaluacion.clasificacion_39 --reclasificar` reclasifica el
corpus con el código del árbol, dentro de una transacción que se revierte, y lo
mide. Antes había que escribir un script suelto cada vez.

## Lo que queda abierto

- **El sartén sigue sin el puente que le hace falta.** César contestó
  `domestico/cocina → «articulos de uso domestico y sus partes»`, y el
  emparejamiento exige las dos palabras. La ficha del sartén dice COCINA, no
  DOMÉSTICO. Leer la barra como «o» sería reinterpretar su respuesta; hay que
  preguntárselo a él.
- **Un puente útil discrimina.** Los que hoy se disparan (`de hierro o acero`,
  `sin galvanizar`) describen medio capítulo. Lo que podría mover la cobertura
  son respuestas que nombren el texto de UNA partida, y eso es vocabulario, no
  código.
