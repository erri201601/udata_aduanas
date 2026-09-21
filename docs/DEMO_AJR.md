# Guion de demo — AJR

> Estado verificado el 8 de septiembre de 2026. Todo lo que aparece aquí lo
> corrí antes de escribirlo. Nada es aspiracional.
>
> **Actualización 21-sep-2026.** Las secciones 3 y 4 se volvieron a correr
> contra el sistema en vivo, con la tarifa completa, el arreglo de la RGI 3 c)
> (#69) y el de acentos en la búsqueda de candidatas (#82). La traza de abajo
> es la que sale hoy, copiada de la ejecución. La sección 7 sigue en pausa.
> Quién es AJR y qué es ANA: `docs/AJR_Y_ANA.md`.

## La decisión de fondo

No enseñes que el sistema encuentra dinero. **Hoy no puede**, y una demo que lo
finge se cae en la primera pregunta.

Enseña lo que sí tiene y nadie más tiene: **un sistema que se niega a
adivinar y que muestra su trabajo hasta la fuente.** Para un agente aduanal
—que firma con su nombre y responde con su patrimonio— eso no es el premio de
consolación. Es el producto.

Si intentas la versión «mira cuánto ahorras», AJR pregunta «¿de dónde sale ese
número?» y la respuesta hoy sería incómoda. Si haces la versión honesta, la
pregunta que provoca es «¿cuándo lo tengo?», que es la que quieres.

---

## 1 · El problema (2 min) — sin computadora

Abre con una pregunta, no con el producto:

> «¿Cuántas veces te ha llegado una clasificación de un despachante y has
> tenido que confiar en que está bien?»

Y el planteamiento:

Un clasificador que devuelve `8471.30.01` con 94% de confianza es fácil de
construir. Y es inservible para quien firma el pedimento, porque no puede
llevar «94%» a una revisión del SAT.

Lo que un agente necesita no es el código. Es **poder defenderlo**: con qué
regla, con qué fuente, en qué versión, vigente cuándo.

---

## 2 · Los datos son reales (2 min)

Enseña la base, no una diapositiva:

```
8,136 fracciones arancelarias   los 97 capítulos de la LIGIE
11,503 NICO
   92 notas de Sección y Capítulo de la LIGIE
      Ley Aduanera
```

El punto que importa: **cada documento se guardó crudo antes de procesarlo,
con su hash.** Si el portal cambia una descripción mañana, tenemos la prueba de
qué decía el día que se leyó.

> «Esto no es un modelo que memorizó la tarifa. Es la tarifa.»

---

## 3 · Clasificación en vivo (4 min) — el corazón

Toma la ficha de un producto y clasifícalo delante de ellos.

Lo que sale no es un código: es una **traza, regla por regla**:

```
RGI 1    10 partidas comprenden la mercancía (8471, 8528, 7321, 8413, 8424,
         8504, 8515, 8519, 8527, 7318). La RGI 1 no la resuelve.
RGI 2    No se presenta incompleta, sin terminar ni desmontada, y no consta
         que sea una mezcla o asociación de materias.
RGI 3a   Las partidas 8471 y 8528 son igual de específicas; la RGI 3 a) no
         las distingue.
RGI 3b   Determinar el carácter esencial exige un juicio material sobre la
         mercancía y no hay intérprete disponible.
RGI 3c   Ninguna regla anterior distinguió. Se aplica la última por orden de
         numeración: 8528. Confianza 0.45, marcada para revisión humana.
RGI 6    Nueve subpartidas de 8528 comprenden la mercancía y ninguna es más
         específica. Falta: «desempate de subpartida por un clasificador».
```

Detente en dos sitios.

**La RGI 2.** La regla no está implementada y aun así se evalúa: el sistema
comprueba si sus condiciones se cumplen y lo dice. No se la salta en silencio.

**Las candidatas de la RGI 1.** Ahí aparecen 7321 —esparcidores de flama—,
8413 —extintores portátiles—, 8515 —cautines— y hasta 7318, tornillos de menos
de ¼ de pulgada. Enséñalo en vez de esconderlo:

> «Ninguna de esas está ahí por error: todas dicen "portátil" o "pulgada" en
> su texto legal. El sistema está leyendo la nomenclatura, no adivinando con
> un modelo. Y fíjense en cuáles puso primero: las dos que importan.»

---

## 4 · El momento en que se niega (3 min) — EL DIFERENCIADOR

Aquí está la demo. No lo pases rápido; es el punto entero.

El sistema termina en `HUMAN_REVIEW_REQUIRED` **sin dar fracción**. Y el porqué
es mejor de lo que parece, porque se frena en dos tiempos:

1. **La RGI 3 c) sí desempata.** Elige 8528 —«la última por orden de
   numeración»— porque eso es lo que prescribe la regla. Pero no se lo queda:
   confianza 0.45 y marcada para revisión humana. Resolvió por la letra, no
   porque alguien entendiera la mercancía.
2. **La RGI 6 ya no puede.** Nueve subpartidas de 8528 comprenden la
   mercancía y ninguna es más específica. Ahí se detiene, y dice qué le
   falta: un desempate de subpartida por un clasificador.

> «No les dio 8528 con un 94% y a correr. Desempató por la letra de la regla,
> lo dijo, y se paró en el punto exacto donde ya no podía seguir sin
> inventar.»

Y aquí está el detalle que vale la demo entera: **hasta hace dos semanas esto
devolvía 8528 como si fuera una respuesta.** La regla se aplicaba bien y el
resultado salía limpio, sin avisar de que el desempate había sido por
numeración.

Y ahora enséñales la nota real, la del Capítulo 84:

> «…herramientas para ser operadas por una persona y que sean **portátiles**.
> 14. En la partida 84.71, no se consideran los aparatos utilizados para la
> comunicación…»

Cuenta lo que pasó de verdad esta semana: una versión anterior cazaba la
palabra «portátiles» y daba la partida por excluida. Excluía la partida
correcta de una computadora portátil, por una frase sobre herramientas de mano.

> «Lo detectamos y lo quitamos. Preferimos que el sistema diga *no sé* a que
> diga algo defendible que no lo es. Una exclusión falsa les descarta la
> partida correcta y clasifica mal con toda la apariencia de rigor.»

Esa frase es la venta. Un competidor habría dejado el `ILIKE` porque «funciona
casi siempre».

---

## 5 · El expediente de defensa (3 min)

Abre el dossier de una decisión. Son diez preguntas, las que hace una
auditoría:

```
qué detectaste · por qué · con qué regla · con qué fuente · qué versión
cuándo era vigente · qué dato usaste · cuánta confianza · cuánto dinero
requiere revisión
```

Y lo que hay que señalar: **las que no puede contestar aparecen listadas como
`unanswered`.** No se rellenan con algo plausible.

> «Un expediente incompleto que se declara incompleto es utilizable. Uno
> completo por invención es una trampa.»

---

## 6 · Pedimento Espejo (3 min)

Corre la revisión de un pedimento. Construye lo que *debería* declararse **sin
mirar lo declarado**, y sólo después compara — para no caer en justificar lo
que ya está ahí, que es el sesgo de cualquier revisor humano.

El resultado de hoy:

```
Sin hallazgos en lo revisable, pero 4 puntos quedaron sin comprobar.
```

Y los cuatro, nombrados uno por uno —léelos tal cual, que están escritos para
que los entienda quien firma—:

- la clasificación no llegó a ser defendible, así que no se puede afirmar que
  lo declarado sea incorrecto;
- no consta el país del proveedor: la partida no está ligada a una factura,
  así que el origen declarado no se pudo contrastar con nada;
- no se conoce qué NOM exige la fracción esperada: falta el Anexo 2.2.1 del
  Acuerdo de la SE;
- no se conocen los identificadores que exige la operación: falta el Apéndice
  8 del Anexo 22.

> «Un pedimento que nadie verificó no está limpio: está sin verificar. Si el
> sistema los mezclara, alguien presentaría ante la autoridad un pedimento sin
> revisar creyendo que pasó el filtro.»

---

## 7 · Qué falta y cuándo (2 min)

Dilo tú antes de que lo pregunten. Enseña el tablero, que declara
`SYNTHETIC DEMO DATA` solo.

| falta | qué desbloquea |
|---|---|
| RGCE 2026 y el resto de la Ley Aduanera | interpretación de notas → clasificaciones cerradas |
| Anexo 2.2.1 de la SE | validación de NOM por fracción |
| Datos reales de AJR | ⏸ **en pausa desde el 14-sep** — no se piden por ahora |

> ⏸ **En pausa desde el 14-sep-2026.** El cierre de abajo y la petición de
> `docs/PETICION_AJR.md` quedan sin usar hasta que Persona 1 retome los
> pedimentos. **No lo digas en la demo.** Se conserva el texto porque el
> razonamiento sigue siendo válido.

Y el cierre, que es una petición concreta:

> «Denos diez pedimentos reales suyos, ya cerrados, de los que ya sepan el
> resultado. Se los devolvemos auditados y comparan. Si no encontramos nada,
> lo dicen y no perdieron nada. Si encontramos algo, lo verifican contra su
> propio expediente.»

Eso convierte la demo en un piloto sin pedirles presupuesto.

**Qué pedirles exactamente:** `docs/PETICION_AJR.md`. No basta con los diez
pedimentos — hace falta la documentación técnica de la mercancía, o estaríamos
comparando contra la fracción que ellos ya declararon.

---

## Preguntas que van a hacer

**«¿Y esto qué tan seguido acierta?»**
La respuesta honesta: *todavía no lo medimos, y por eso no se lo voy a decir.*
Estamos construyendo el conjunto de casos con resultado conocido para poder
darle un número con respaldo. Cualquiera que le dé un porcentaje hoy se lo está
inventando.

**«¿Usa inteligencia artificial?»**
Para leer fichas técnicas y extraer atributos, sí. **Para decidir la fracción y
para calcular dinero, no.** El dinero se calcula con aritmética exacta y la
clasificación la determinan las reglas contra la tarifa. El modelo puede
sugerir; si sugiere algo que no está en la tarifa vigente, se rechaza.

**«¿Reemplaza a mi clasificador?»**
No. Le prepara el expediente y le señala dónde mirar. La firma sigue siendo
suya, y por eso el sistema está construido para que pueda defenderla.

**«¿Mis datos salen de aquí?»**
Hoy todo corre en infraestructura nuestra, cerrada, sin exposición a internet.
Cuando haya datos suyos, eso se define por contrato antes de cargar nada.

---

## Antes de entrar

- [ ] `make up` y `curl` a `/health/ready` — los cuatro servicios en verde
- [ ] La API responde en la IP de Tailscale, **no** en `localhost`
- [ ] Clasifica el producto una vez en privado: si el resultado cambió, quieres
      enterarte antes que ellos
- [ ] Ten la nota del Capítulo 84 abierta en otra pestaña
- [ ] El tablero declarando `SYNTHETIC DEMO DATA`

**No improvises con un producto que traigan ellos.** Ofrécelo como el piloto
del punto 7: «démelo por escrito y se lo devuelvo auditado esta semana». Un
fallo en vivo con su propio producto cuesta más que la buena impresión de la
espontaneidad.
