# Petición a AJR — de pedir documentos a pedir juicio

> ❌ **CANCELADA el 23 de septiembre de 2026. No enviar.**
> **AJR no va a entregar más pedimentos reales** (Persona 1, 23-sep). Ésa es la
> razón por la que el corpus espejo se generó por nuestra cuenta y por la que
> toda la capa operativa está marcada `SYNTHETIC`: 16 pedimentos y 181
> partidas, sin una sola fila real.
>
> El documento **no se borra**: lo que pedía —y sobre todo el análisis de por
> qué un pedimento sin su ficha técnica no sirve— sigue siendo correcto, y hay
> que conservarlo por si aparece otra fuente de datos reales. Lo que cambia es
> a quién se le pide y qué. Ver §0.

> Preparado el 9 de septiembre de 2026. Los campos de este documento salen de
> `database/models/operational.py` y del camino que recorre
> `POST /pedimentos/{id}/review`, no de una lista de deseos.

---

## 0. Lo que la sustituye: pedir juicio, no documentos

Pedir **pedimentos** es pedir que salgan documentos confidenciales de su casa.
Es un no razonable y no vale la pena insistir.

Pedir **juicio** es otra cosa, y sirve igual para lo que necesitamos:

> ¿Nos revisa estas diez clasificaciones y nos dice si están bien?

No sale ningún documento suyo. No hay riesgo de confidencialidad. Le cuesta
media hora a un clasificador. Y es **exactamente** lo que el proyecto necesita,
porque el problema nunca fue tener pedimentos: era no tener un dictamen humano
contra el que medir.

### Por qué eso basta

La capa operativa puede seguir siendo sintética. **El juicio de clasificación
no tiene por qué serlo.** Cuando alguien calificado dictamina «esta mercancía
va en 7323», esa fila entra como `HUMAN_VALIDATED` —uno de los cinco valores
del §9— y deja de ser `SYNTHETIC`. Contra eso sí se mide precisión.

Hoy hay **cero** filas `HUMAN_VALIDATED` en todo el sistema. Es la casilla que
nunca hemos usado y la que desbloquea el número de verdad.

### Los primeros diez casos ya existen

`hs_accuracy` dio **0 de 10** en su primera corrida (#125): diez desacuerdos
entre lo que el motor clasificó y lo que dice el corpus. Ésos son los diez que
hay que poner delante de un clasificador. No hay que fabricar nada.

### Y si AJR también dice que no

La pregunta pasa a ser **a quién se le paga media hora de revisión**, no qué
empresa nos cede diez expedientes. Es la única dependencia externa que le queda
al proyecto, y acaba de encogerse de «diez expedientes de una empresa» a
«media hora de una persona con firma».

---

## Por qué existía esto

`DEMO_AJR.md` cerraba pidiendo «diez pedimentos reales suyos, ya cerrados».
Este documento era lo que faltaba: **qué necesitábamos exactamente y en qué
forma**, porque «diez pedimentos» a secas devuelve diez PDF que no podemos
ingerir, y el segundo intento cuesta el doble de credibilidad que el primero.

Ese razonamiento se conserva entero por si aparece otra fuente. Lo que ya no
aplica es el destinatario.

El motor está en **83.33 % (±9.86) sin validar**. Ese número no se mueve con
más código: se mueve cuando alguien calificado revise mercancía real.

---

## 1. El mensaje

> Para poder decirles con qué precisión clasifica el sistema, necesitamos
> contrastarlo contra casos donde el resultado ya se conoce.
>
> ¿Nos pueden dar **diez pedimentos suyos ya cerrados**, de los que ustedes ya
> sepan el resultado? Se los devolvemos auditados y comparan. Si no
> encontramos nada, lo decimos y no perdieron nada. Si encontramos algo, lo
> verifican contra su propio expediente.
>
> Para que el ejercicio sirva necesitamos, además del pedimento, **la
> documentación técnica de la mercancía** — la misma que usó su clasificador
> para decidir la fracción. Sin ella estaríamos comparando contra la fracción
> que ustedes ya declararon, que es justo lo que queremos no hacer.

La última frase no es un tecnicismo y conviene decirla en voz alta: **si sólo
vemos la fracción declarada, no estamos midiendo nada.** El Pedimento Espejo
construye lo que *debería* declararse **sin mirar lo declarado**, y sólo
después compara. Para construirlo necesita la mercancía, no el resultado.

---

## 2. Qué necesitamos por cada pedimento

### 2.1 El pedimento

| Campo | ¿Obligatorio? | Para qué |
|---|---|---|
| Número de pedimento | sí | identificarlo |
| Fecha de operación | **sí** | decide qué normas y qué tarifa se aplican (§14). Sin ella no podemos evaluar sin arriesgar el anacronismo |
| Aduana / sección · clave · régimen | recomendable | cruce con los catálogos del Anexo 22 ya cargados |
| Tipo de operación | sí | importación o exportación |
| Moneda y tipo de cambio | sí | el dinero es determinista, no se estima |
| Valor en aduana y total de contribuciones | recomendable | cuantificar impacto |

### 2.2 Cada partida del pedimento

| Campo | ¿Obligatorio? | Para qué |
|---|---|---|
| Número de línea | **sí** | los hallazgos se cuelgan de la partida |
| Descripción | **sí** | punto de partida de la clasificación |
| Fracción declarada + NICO | **sí** | es *lo declarado*: la mitad que se compara al final |
| Cantidad y unidad comercial | sí | |
| País de origen | sí | preferencias y regulaciones |
| Valor en aduana de la partida | recomendable | reparto del impacto |
| IGI e IVA de la partida | recomendable | contraste con el cálculo determinista |
| NOM aplicadas e identificadores | recomendable | hoy no podemos verificarlos y lo declaramos como hueco |

### 2.3 La mercancía — **esto es lo que suele faltar**

Por cada partida, lo que su clasificador tuvo delante:

- ficha técnica, hoja de especificaciones o catálogo del fabricante
- marca, modelo, fabricante
- factura comercial si describe la mercancía
- fotografías, si es lo que hubo

Sirve escaneado. El sistema lee imágenes y fichas y extrae los atributos
declarando de dónde sale cada uno; **lo que no aparece se marca ausente, no se
inventa**.

### 2.4 El resultado conocido

Lo que convierte esto en verdad conocida y no en otro caso más:

- ¿el pedimento pasó sin observación de la autoridad?
- ¿hubo rectificación, PAMA o corrección posterior? ¿en qué partida y por qué?
- si hubo desacuerdo interno sobre alguna fracción, cuál y cómo se resolvió

Un pedimento cerrado **sin observación** es una señal; uno **corregido** vale
todavía más, porque nos dice cuál era la respuesta correcta.

---

## 3. Formato

En orden de preferencia, y cualquiera sirve:

1. **Exportación del sistema de despacho** en CSV o Excel, una fila por
   partida. Es lo más barato para ellos y lo más directo para nosotros.
2. **XML del pedimento**, si su sistema lo emite.
3. **PDF**. Se puede, con más trabajo de nuestro lado; hay que decirlo antes
   para no prometer plazos que no se cumplen.

Las fichas técnicas, como estén.

---

## 4. Lo que les devolvemos

Por cada partida:

- la fracción que el sistema construyó **sin ver la declarada**, con la traza
  regla por regla de las RGI
- el expediente de defensa: las diez preguntas del §49, con las que no podemos
  contestar marcadas como `unanswered` en vez de rellenadas
- las divergencias contra lo declarado, si las hay
- **y lo que no pudimos verificar, contado aparte.** Un pedimento que nadie
  verificó no está limpio: está sin verificar

Sobre el acierto no vamos a dar un porcentaje hasta tener esto. Cualquiera que
dé uno hoy se lo está inventando.

---

## 5. Lo que van a preguntar

**«¿Mis datos salen de aquí?»** Hoy todo corre en infraestructura nuestra,
cerrada, sin exposición a internet. Cuando haya datos suyos, eso se define por
contrato **antes** de cargar nada.

**«¿Cuánto tardan?»** Depende del formato. Con exportación tabular, días. Con
PDF, más — y conviene decirlo antes.

**«¿Y si encuentran errores nuestros?»** Se los decimos a ustedes y a nadie
más. El objetivo es medir el sistema, no auditar a su equipo.

---

## 6. Antes de cargar nada

- [ ] Definido por escrito el tratamiento de los datos
- [ ] Confirmado si son datos reales o anonimizados
- [ ] **`data_origin` decidido — requiere aprobación de Persona 1.** Los cinco
      valores cerrados son `OFFICIAL`, `PUBLIC`, `LICENSED`, `SYNTHETIC` y
      `HUMAN_VALIDATED`. No es `SYNTHETIC` (son reales), no es `OFFICIAL` (no
      los publica una autoridad) y no es `PUBLIC` (no son públicos).
      `LICENSED` es el único que encaja —dato de un tercero cedido bajo
      acuerdo— y conviene confirmarlo **antes** de la primera fila:
      **marcarlo mal es peor que no cargarlo**, porque el origen se propaga a
      toda la evidencia que se construya encima. Si ninguno encaja, es
      `ARCHITECTURE_DECISION_REQUIRED`: la regla 3 prohíbe inventar un sexto
      valor sin aprobación
- [ ] `is_simulation = false`, a diferencia de todo lo que hay hoy en la base
