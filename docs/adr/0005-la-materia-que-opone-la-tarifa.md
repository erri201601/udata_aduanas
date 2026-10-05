# ADR 0005 — La materia que la propia tarifa opone entre hermanas

- **Fecha:** 2026-10-05
- **Estado:** aceptado (2026-10-05)
- **Decide:** Persona 1
- **Medido por:** el motor contra las 126 partidas limpias del corpus

## Contexto

### El caso

```
FREGADERO DE ACERO INOXIDABLE AISI 304, UNA TINA, 600 X 500 X 220 MM
declarada: 73241001
material (OBSERVED): «acero inoxidable AISI 304»

RGI 3c  →  elige la partida 7324
RGI 6   →  «Varias subpartidas de 7324 comprenden la mercancía
           (732410, 732421, 732429, 732490) y ninguna es más específica.
           El motor no elige entre ellas.»
```

Las cuatro, como las recibe el motor —con el guion ya puesto delante
(ADR 0004)— y con su especificidad:

```
732410  spec 2  «Fregaderos (piletas de lavar) y lavabos, de acero inoxidable.»
732421  spec 2  «Bañeras. De fundición, incluso esmaltadas.»
732429  spec 0  «Bañeras. Las demás.»
732490  spec 0  «Los demás, incluidas las partes.»
```

El empate es real: **dos calificativos cada una**. Y el motor hace bien en
negarse, porque contar calificativos no es una razón que un agente aduanal
firme — eso ya está decidido y documentado en `_unica_o_mas_especifica`, a
raíz del caso de la vajilla de Talavera.

### Por qué las dos reglas que ya existen no lo resolvían

**`_material_contradice`** no lo ve. Su catálogo `_FAMILIAS` mete `acero`,
`hierro` y `fundicion` en una sola familia «ferroso». Esa es la granularidad
**correcta** para el texto de la partida —«artículos de higiene o tocador […]
de fundición, hierro o acero»— y demasiado gruesa para distinguir dos
subpartidas suyas.

**`_el_grupo_la_describe`** no lo ve, y también por una razón buena. Sólo mira
el encabezado de guion, nunca el texto completo, porque la primera versión
miraba el texto entero y clasificó un cable de acero en «De acero **sin
recubrimiento**» — afirmando una ausencia que la ficha no dice. 732410 no tiene
encabezado de guion: cuelga directa de la partida.

### Lo que el bucle de captura dijo por su cuenta

`apps/evaluacion/preguntas_pendientes.py`, que ordena las preguntas por cuántos
casos desatasca cada una, devolvía **una sola pregunta para 15 casos**:

```
La ficha dice: «acero inoxidable AISI 304»
La tarifa exige: «De fundición, incluso esmaltadas»
¿Son lo mismo?   [sí / no]
```

Y ahí está el punto de esta decisión: **esa pregunta no la tiene que contestar
una persona.** La respuesta está en la nomenclatura, dos líneas más arriba.

## Decisión

Cuando dos posiciones **hermanas** nombran materias distintas, la nomenclatura
ya decidió que en ese nivel la materia separa. Una mercancía cuya materia
consta y coincide con una de ellas **no puede ser** la otra.

No es un criterio del motor: es el texto legal de al lado. La LIGIE se tomó la
molestia de abrir 732410 «de acero inoxidable» junto a 732421 «De fundición»;
al hacerlo dijo que un artículo de higiene inoxidable va en la primera.

### Cómo se implementa

`_MATERIAS` es un catálogo de términos **literales** —más fino que
`_FAMILIAS`, que no se toca— y se lee en una dirección: si la ficha declara la
clave, las posiciones que nombren cualquiera de sus valores son posibles.

```
«acero inoxidable»  →  {acero inoxidable, acero}     el inoxidable ES acero
«fundicion»         →  {fundicion}                   y no es acero, ni al revés
«laton»             →  {laton, cobre}
```

Los términos se reconocen de más largo a más corto y se consume cada
coincidencia, o «de acero inoxidable» se leería también como «acero» a secas y
la distinción se perdería justo al interpretarla.

### Las tres puertas que lo hacen seguro

1. **Ninguna hermana nombra la materia de la ficha → no se descarta nada.** Sin
   esta puerta la regla afirmaría que la tarifa distingue por materia en
   niveles donde no lo hace, y quitaría la posición correcta por no repetir una
   palabra. Es el error del cable de acero, otra vez.
2. **Una hermana que no nombra materia nunca se descarta.** «Las demás» no
   afirma nada que contradecir, y es precisamente la que recoge lo que no
   encaja en las otras.
3. **La materia sale de un hecho sólido de materia, nunca de la descripción
   comercial.** Un cable de acero con alma de fibra nombra dos materias ahí, y
   adivinar cuál manda descartaría la posición correcta. Mismo criterio que
   `_familia_de_la_mercancia`.

### El descarte se enseña

Cuando el motor manda a revisión, `candidate_codes` lleva la lista **completa**
y la traza dice qué quitó y por qué. Un candidato que desaparece sin decirlo es
peor que uno que sobra: quien revisa necesita ver también lo que el motor
descartó para poder discutirlo.

La pregunta del bucle de captura se formula sólo sobre las posibles.
Preguntarle a una persona por una posición que la tarifa ya descartó gasta su
tiempo.

## Consecuencias

### Medido sobre las 126 partidas limpias del corpus

|  | antes | ahora |
|---|---|---|
| contestó | 16 | **25** |
| acertó | 16 | **25** |
| falló | 0 | **0** |
| precisión | 100 % | **100 %** |
| cobertura | 12.70 % | **19.84 %** |
| margen al 95 % | ±9.68 | **±6.66** |

Preguntas pendientes del bucle de captura: **1 → 0**.

### Lo que sigue atascado

Las 101 abstenciones que quedan son todas el mismo estado —empate de
subpartida— concentrado en cinco partidas:

```
41  7312   cables y trenzas de acero
32  8481   grifería y válvulas
31  7305   tubos de gran diámetro
15  7323   artículos de uso doméstico
12  7318   tornillería
```

Cada una pide su propio análisis y su propia medición. **Una regla por vez:**
tres veces en la sesión del 4/5 de octubre una mejora al motor produjo
respuestas equivocadas que sólo cazó la medición —un ranking de términos que
bajó la precisión del 100 % al 50 %, una condición numérica que dio tubos de
petróleo para una tubería de fluidos, y un «describe la mercancía» léxico que
eligió «sin recubrimiento» para un cable—. Las tres se revirtieron.

### Lo que esta regla NO hace

No elige. Sólo descarta, y descartar sólo puede resolver cuando lo que queda lo
resuelven las reglas de siempre. Si tras el descarte siguen empatadas varias,
el motor sigue negándose — que es la respuesta correcta.
