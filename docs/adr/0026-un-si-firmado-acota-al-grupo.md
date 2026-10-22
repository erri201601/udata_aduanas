# ADR 0026 — Un «sí» firmado acota al grupo de guion en la RGI 6

- **Fecha:** 2026-10-21
- **Estado:** aceptado (2026-10-21, por delegación de Persona 1)
- **Decide:** Persona 1, que delega lo técnico; queda escrito aquí.
- **Sigue a:** ADR 0004 (grupos de guion), ADR 0007 y ADR 0025 (el puente no
  entra en la búsqueda de partida).

## Contexto

Cuatro familias del corpus se abstienen siempre: las dos de tuberías, el
sartén y el utensilio. Suman unos 43 casos y son la mayor parte del 37 % que
falta de cobertura.

Antes de pedirle respuestas a César se simularon cuatro «no» plausibles en una
transacción revertida: **resolvían 0 casos**. Había tres causas, todas del
motor:

1. **Un «sí» firmado (`EQUIVALE`) no elegía nada.** Sólo servía para no volver
   a preguntar. La tubería dice «conducción de fluidos»; el encabezado de guion
   que separa sus subpartidas dice «oleoductos o gasoductos». Una respuesta que
   uniera los dos no tenía ningún efecto.
2. **Un «no» firmado se evaluaba sobre las siete subpartidas de 7305.** Sólo
   resuelve si deja una, y quitar una de siete deja seis.
3. **El motor podía elegir justo lo que una persona declaró imposible.** Con
   varias supervivientes se vuelve a la lista entera, para no desempatar por
   especificidad entre ellas, y el desempate podía caer en la descartada.
   Simulado: con «HFW no es arco sumergido» firmado, 11 tuberías HFW salían
   7305.11, «con arco sumergido».

## Decisión

En la RGI 6:

1. **Un «sí» firmado acota al grupo de guion** (`_una_respuesta_la_pone_en_el_grupo`),
   igual que si la ficha dijera la palabra. Tiene tres límites:
   - **Sólo el encabezado de guion, nunca el texto propio de una subpartida.**
     César firmó «acero inoxidable» = «de hierro o acero». Aplicado al texto
     propio, metería al sartén en 7323.94 («esmaltados») en vez de 7323.93
     («De acero inoxidable»).
   - **Sólo lo firmado** (`HUMAN_VALIDATED`). Los puentes nuestros abren medio
     capítulo (ADR 0025).
   - **Sólo si esta ficha dice el término** (`la_ficha_dice`).
2. **Primero el grupo, después lo firmado.** Dentro del grupo, un «no» sí puede
   dejar una sola. Las de fuera se registran como descartadas por `GRUPO`, con
   su motivo.
3. **Lo que una persona declaró imposible no se elige.** Si el desempate cae en
   una subpartida descartada por respuesta firmada, el motor se abstiene.
4. **El residual puro no sostiene el empate.** Es la misma regla de las
   fracciones (#191), ahora también en subpartidas y sobre el texto propio. Sólo
   se aplica si un descarte firmado quitó algo y queda una que califica que la
   ficha respalda.

## Medición

Reclasificando las 188 partidas en una transacción revertida
(`clasificacion_39 --reclasificar`):

```
                                    contestó  acertó  falló  cobertura
develop                              104/164     100      4    63.41 %
este código, sin respuestas nuevas   104/164     100      4    63.41 %
este código + 3 respuestas simuladas 127/164     123      4    77.44 %
```

- **Sin respuestas nuevas, el cambio no mueve nada.** Comparado producto a
  producto contra `develop`, hay 0 diferencias en 187 productos.
- **Con tres respuestas, entran 23 aciertos y ningún error.** Las respuestas
  simuladas, que **todavía nadie ha dado**, son:
  - «conducción» **sí** es «oleoductos o gasoductos»;
  - «HFW» **no** es «arco sumergido»;
  - «helicoidal» **no** es «soldados longitudinalmente».
- **Las tuberías con dictamen:** 30 de 30 bien.
- **Los 4 fallos son los de siempre:** cables cuya declaración sintética dice
  `73121099` y el motor `73121005`, la fracción que César dio por buena el
  6-oct.

**La cobertura no sube hasta que César conteste.** Las respuestas se le piden
aparte, con lo que resuelve cada una.

## Ruido de la medición

Dos corridas del mismo código pueden diferir en un caso: 103 frente a 104. La
causa está en el log: `rag.embedder.degradado`. Cuando falla la llamada al
proveedor de vectores, el motor sigue sólo por términos y puede cambiar una
decisión. Por eso la comparación que vale es la producto a producto, y una
diferencia de ±1 en el total no se interpreta sin ella. Es también la
diferencia de un caso que el ADR 0025 dejó sin aislar.

## Lo que no resuelve

- **El sartén y el utensilio.** No llegan a la partida 7323: la búsqueda de
  partida se queda en tubos y tornillos (ADR 0007). Esto actúa al elegir
  subpartida, un nivel más abajo.
- **La olla de presión.** Su ficha no trae el material, y eso es un dato del
  proveedor.
