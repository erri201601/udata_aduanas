# ADR 0016 — El NICO cuando la LIGIE lo distingue sólo por medidas

- **Fecha:** 2026-10-20
- **Estado:** aceptado (2026-10-20, por delegación de Persona 1)
- **Decide:** Persona 1, que delega lo técnico; queda escrito aquí.
- **Sigue a:** ADR 0013, «Lo siguiente»: bajar la abstención exige una regla
  para elegir entre varios NICO, medida antes y después contra los veredictos
  de César.

## Medición antes de decidir

En la base compartida hay 75 fichas en las que César firmó un NICO dentro de
una fracción que tiene varios. Agrupadas por fracción:

| Fracción   | Cómo distinguen sus NICO                         | Fichas | César |
|------------|--------------------------------------------------|-------:|------:|
| 7305.11.02 | espesor de pared y diámetro exterior             |      5 |    02 |
| 7305.12.91 | espesor de pared y diámetro exterior             |     11 |    02 |
| 7305.19.99 | espesor de pared                                 |     14 |    01 |
| 7312.10.05 | diámetro                                         |     14 |    02 |
| 7312.10.99 | diámetro **y** materia, uso, presentación        |     18 | 05/07 |
| 7615.10.02 | tipo de artículo                                 |     12 |    01 |
| 6912.00.99 | uso                                              |      1 |    01 |

En las cuatro primeras, cada NICO salvo «Los demás» es un rango numérico de
una medida que la ficha trae observada (`espesor_pared_mm`,
`diametro_exterior_mm`, `diametro_mm`). En las otras tres no.

## Decisión

Una regla, `core.classification.nico_por_medida`, que actúa sólo si se cumple
todo esto:

1. **Todos** los NICO de la fracción, salvo «Los demás», son condiciones
   numéricas que el módulo entiende por completo. Si uno solo dice algo más
   (por ejemplo, «Cables plastificados» o «De acero, …»), no se elige: mirando
   sólo números no se puede descartar un NICO que no habla de números.
2. La ficha trae, como `OBSERVED` o `EXTRACTED`, **cada** medida que mencionan.
   No basta una inferida ni sirve una ausente, y no se usan alias: el
   «diámetro» de un cable no es el «diámetro exterior» de un tubo.
3. Si caben varios, gana el **más específico**: aquel cuya región está
   contenida en la de todos los demás. La LIGIE solapa 7305.11.02 NICO 01
   («espesor de pared inferior a 50.8 mm») con el NICO 02 («de 4.77 a 25.4 mm,
   diámetro exterior hasta 1,219.2 mm»). El 02 está dentro del 01, y es el que
   firmó César. Si ninguno está contenido en los demás, no se elige.
4. «Los demás» sólo se elige cuando ningún otro cabe.
5. Todo en `Decimal`, respetando si cada límite es «inferior a» o «inferior o
   igual a».

`nico_de` aplica primero la regla del NICO único (ADR 0013) y después ésta. El
motivo, ya sea la elección o la abstención, va al razonamiento persistido.

## Medición después (§39, `apps.evaluacion.clasificacion_39`)

| | Antes | Después |
|---|---:|---:|
| NICO contestados / medibles | 40 / 98 | **68 / 98** |
| Aciertos | 40 | **68** |
| Fallos | 0 | **0** |
| Abstenciones (varios NICO sin regla) | 58 | **30** |
| Precisión de fracción | 98 / 98 | 98 / 98 |

Las 30 que quedan son exactamente 7312.10.99, 7615.10.02 y 6912.00.99, donde
la regla se abstiene a propósito.

## Lo que no cambia

- El Espejo (`_nico_esperado`, detección §26) no usa esta regla. Usarla para
  detectar `WRONG_NICO` es otra regla, y se mide aparte.
- Las decisiones ya persistidas no cambian. El NICO aparece en las nuevas
  clasificaciones o al reclasificar.
- No cambia `requires_human_review`, ni el estado, ni la bandeja.

## Lo siguiente

- Los 3 FN de la detección son `WRONG_NICO` sin detector. Con esta regla, el
  Espejo podría esperar un NICO por medidas y señalar el declarado distinto.
  Se mide contra el ground truth antes de activarlo.
- 7312.10.99 necesita distinguir materia y presentación («latonado»,
  «plastificados»). Eso no es una regla numérica.
