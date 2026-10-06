# ADR 0007 — La búsqueda de partida no se arregla tocando los términos

- **Fecha:** 2026-10-05
- **Estado:** aceptado (2026-10-05)
- **Decide:** Persona 1 (delegado)
- **Medido por:** el motor contra las 168 partidas con fracción fiable del corpus

## Contexto

César entregó el 5-oct un dictamen de 49 casos y, en él, cinco reglas
prácticas. La primera dice:

> 1) Primero decidir si la mercancía completa cumple la partida.
> 2) No clasificar por un componente incidental: una válvula de seguridad no
>    convierte una olla en grifería.

El motor no lo hace. Tres casos del corpus que él dictaminó como `73239305`
—sartén de acero inoxidable— acaban buscando entre tubos y tornillos:

```
SARTEN DE ACERO INOXIDABLE PARA COCINA, DIAMETRO 28 CM, MANGO DE ACERO
términos: SARTEN ACERO INOXIDABLE COCINA DIAMETRO MANGO
candidatas: 7304 (tubos sin soldadura) · 7305 (los demás tubos)
            7306 (los demás tubos) · 7318 (tornillos)
            ← la 7323 no llega a ser candidata
```

La causa inmediata es conocida: la búsqueda es una bolsa de palabras con un
tope de seis términos (`MAX_TERMINOS`), y las palabras que sobreviven al tope
no son las que distinguen.

## Lo que se probó, y por qué se descartó

Tres intervenciones sobre la selección de términos. Las tres se midieron
contra el corpus completo —reclasificando los 181 productos— y las tres se
revirtieron.

### 1. Deduplicar ignorando el acento

`palabras_de` deduplica con `casefold()`, y `«DOMESTICO».casefold()` no es
`«DOMÉSTICO».casefold()`. Tres fichas del corpus escriben la misma palabra de
las dos formas y gastaban dos de los seis términos en una sola. La búsqueda ya
compara sin acentos a los dos lados (`unaccent` en `_casa`), así que el
duplicado no aportaba nada.

El arreglo es correcto en sí mismo y hace lo que promete: las candidatas de
esos tres casos pasan de **nueve partidas a una, la 7323**, que es la correcta.

```
                 contestó  acertó  falló  precisión  cobertura
antes                  70      70      0   100.00 %    41.67 %
con el arreglo         73      70      3    95.89 %    43.45 %
```

Los tres fallos son los tres mismos casos: con la partida ya acertada, la
RGI 6 elige `73231001` —«lana de hierro o acero; esponjas, estropajos»— sobre
`73239305` —«De acero inoxidable»—, porque la primera cuelga directa de la
partida y la segunda de un grupo «Los demás:» (ADR 0004 y el desempate del
PR #184). Para un estropajo eso es correcto; para un sartén, no.

**Convierte tres negativas honestas en tres fracciones equivocadas**, que es
exactamente lo que el código ya tiene escrito que no es una mejora.

### 2. Dar prioridad a los datos técnicos sobre la prosa del resumen

La regla 3 de César dice «usar los datos técnicos que separan subpartidas». El
resumen es la descripción del pedimento —prosa de formulario— y los hechos
salen de la ficha técnica, así que parecía claro que los hechos debían llenar
el tope primero.

Es peor, y por un caso que lo cierra: la olla de presión de aluminio. Su
`material` está sembrado vacío, y la palabra `ALUMINIO` sólo está en el
resumen. Con los hechos delante, la olla pierde su materia y pasa de resolver
`76151002` —correcto— a `INSUFFICIENT_INFORMATION`. El «utensilio» se va a
`69111001`, vajilla de **porcelana**, porque sin `ACERO` lo único que queda es
`cocina`.

Ni resumen-primero ni hechos-primero es correcto: depende del producto.

### 3. Conectar `poder_de_discriminacion`, la medida que ya existía

`TariffCatalogRepository.poder_de_discriminacion` mide cuántas posiciones de la
tarifa engancha cada término y lleva su medición escrita en el docstring —«26 %
no existen en la tarifa, 13 % enganchan más de sesenta posiciones, 60 %
útiles»—. Aparecía **una vez en todo el repositorio: su propia definición**.
Ni un test la llamaba.

Medido sobre el «utensilio», dice exactamente lo que sobra:

```
ARTICULO        185 posiciones   no separa nada
UTENSILIO         0              no existe en la tarifa
ACERO            89              no separa nada
DOMESTICO        19   útil
MATERIAL         22   útil
ESPECIFICADO      4   útil
INOXIDABLE       19   útil   ← se quedaba fuera del tope
cocina           12   útil   ← se quedaba fuera del tope
```

Aplicada como banda —fuera lo de 0 y lo de más de 60, como describe su propio
docstring— la precisión se mantiene y la cobertura se desploma:

```
                 contestó  acertó  falló  precisión  cobertura
antes                  70      70      0   100.00 %    41.67 %
con la banda           41      41      0   100.00 %    24.40 %
```

Veintinueve aciertos perdidos. `ACERO` engancha 89 posiciones y por la medida
«no separa nada», pero es la palabra que nombra la materia y sin ella el motor
no encuentra la partida de nada de acero. La medida acierta al decir que un
término genérico no discrimina **por sí solo**; se equivoca al concluir que se
puede tirar.

Probado también como orden en vez de banda: peor. Deja `ALUMINIO` (41) en el
puesto ocho de la olla, fuera del tope, mientras entran cinco términos de tres
y cuatro posiciones. Un término que engancha poco no es mejor que el que nombra
la materia.

## Decisión

**La selección de términos se queda como está.** Ninguna de las tres
intervenciones entra. Se conserva en este documento la medición de las tres
para que no se repitan.

El tope de seis y la bolsa de palabras son un óptimo local: cada ajuste
razonable que se le hace lo empeora, porque el problema no es *cuáles* seis
palabras llegan, sino que **la pertenencia a una partida no es una cuestión de
palabras compartidas**. Un sartén no comparte ninguna palabra con la partida
7323 —la tarifa no dice «sartén» en ningún sitio: `poder_de_discriminacion` le
da cero— y sí comparte «acero» y «diámetro» con tres partidas de tubos.

## Consecuencias

- Los 8 casos de la bandeja del sartén y el «utensilio» siguen sin salida. Sus
  preguntas no mueven nada, y eso consta.
- `poder_de_discriminacion` sigue sin usarse. Queda documentado que no es por
  olvido: conectarla como banda cuesta 29 aciertos.
- La vía que queda es la que el §27 del maestro ya asigna al RAG: «la semántica
  la aporta el RAG». Decidir la partida de la mercancía completa es un problema
  de significado, no de vocabulario, y es donde los embeddings tienen algo que
  aportar que una bolsa de palabras no.
- Eso es un cambio de arquitectura de la búsqueda de partida, no un ajuste, y
  pide su propio ADR y su propia medición antes de tocar nada.
