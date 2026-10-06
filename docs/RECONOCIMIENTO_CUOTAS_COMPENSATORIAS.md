# Reconocimiento — Cuotas compensatorias: ¿alguna partida del corpus las necesita?

> Sin migración ni carga nueva. Sólo lectura de fuentes del DOF reales +
> cruce contra el corpus sintético ya cargado, como pidió Persona 1 antes
> de decidir si se abre esta tarea. 2026-10-06.

## La pregunta que hay que contestar antes de migrar

Erick, al asignar esta tarea (después de tipo de cambio): *"¿alguna
partida del corpus tiene un origen y una mercancía sujetos a cuota? Si
ninguna, el reconocimiento lo dice y la carga espera."* Mismo criterio que
Apéndice 8 ("no hay fila sin consumidor posible").

`docs/PROMPT_P2.md` ya advierte que esta fuente es distinta a las
anteriores: **no es un documento único** (como el Anexo 22 o la serie
diaria de Banxico) — es un conjunto abierto de "resoluciones definitivas
del DOF", una por producto+origen+exportador, publicadas en años distintos,
muchas bajo revisión activa ("examen de vigencia") en cualquier momento.
`PedimentoItem` ya tiene los dos campos que hacen falta para cruzar:
`country_of_origin` (ISO-2) y `declared_fraction_code`/`tariff_fraction_id`
— no hace falta ninguna columna nueva para esta pregunta.

## Qué tiene el corpus (16 pedimentos, consulta directa a la base local)

21 combinaciones distintas (origen, fracción), repartidas en 4 países de
origen y 10 fracciones de 8 dígitos:

| Origen | Fracciones declaradas |
|---|---|
| `BR` (Brasil) | 6911.10.01, 6912.00.99, 7312.10.99, 7324.10.01 |
| `CN` (China) | 6911.10.01, 6912.00.99, 7305.12.91, 7312.10.99, 7323.10.01, 7615.10.02 |
| `IN` (India) | 6911.10.01, 7305.11.02, 7312.10.99, 7323.10.01, 7323.93.05, 7324.10.01 |
| `TR` (Turquía) | 6912.00.99, 7305.19.99, 7312.10.99, 7324.10.01, 7615.10.02 |

Todas las operaciones del corpus caen en agosto de 2026 (03-ago a 31-ago).
Esa ventana importa: una cuota real puede haber empezado o terminado
antes, y versionar mal aquí es exactamente el error que el §5 de
CLAUDE.md prohíbe ("nunca evalúes una operación histórica con regulación
posterior" — y su espejo: tampoco con una que ya terminó).

## Tres cruces verificados contra el DOF real (no asumidos, no inventados)

### 1. `CN` + `7312.10.99` (cable de acero) — **VIGENTE, coincide**

Cuota compensatoria de **2.58 USD/kg** a cables de acero originarios de
China. Prórroga de 5 años publicada en el DOF el 2026-04-09 (entra en
vigor 2026-04-10), contados desde el 2024-12-17. Cubre las operaciones de
agosto de 2026 del corpus sin ambigüedad.

- [DOF, resolución final de examen de vigencia, 2026-04-09](https://www.dof.gob.mx/nota_detalle_popup.php?codigo=5619643)
- Corroborado de forma independiente por tres fuentes más (idconline,
  reportacero, stratego-st) con la misma cifra de 2.58 USD/kg.

### 2. `CN` + `7615.10.02` (artículos para cocinar de aluminio) — **VIGENTE, coincide**

Cuota compensatoria (hasta **7.73 USD/kg** según la nota de Milenio citada
abajo) a ollas/sartenes de aluminio originarios de China, impuesta por
resolución final de 2023-03-31. Examen de vigencia iniciado el
2026-09-29 — la cuota **sigue vigente durante la tramitación del
examen**, así que cubre también las operaciones de agosto de 2026
(anteriores al inicio del examen, bajo la cuota ya impuesta desde 2023).

- [Resolución final 2023-03-31 (gob.mx)](https://www.gob.mx/cms/uploads/attachment/file/814244/publicaciones_dof_articulosparacocinardealuminio_310323.pdf)
- [México mantiene cuota de hasta 7.73 USD/kg a sartenes chinos — Milenio](https://www.milenio.com/negocios/mexico-mantiene-cuota-7-73-dolares-kilo-sartenes-chinos)

### 3. `IN` + `7305.11.02` (tubería de acero al carbono con costura) — **VIGENTE, coincide**

Cuota compensatoria de **81.61 USD/tonelada** (cifra nombrada para el
exportador Welspun Corp — exportador específico, no un monto único por
país) a tubería de acero al carbono con costura longitudinal recta y
helicoidal originaria de Estados Unidos **e India**, fracciones
7305.11.02, 7305.12.91 y 7305.19.99. Examen de vigencia iniciado el
2026-04-06; la cuota sigue vigente durante la tramitación.

- [Inicio de examen de vigencia, DOF 2026-04-06](https://www.dof.gob.mx/nota_detalle.php?codigo=5784087&fecha=06%2F04%2F2026)

**Importante, verificado en la misma resolución:** este examen es
**EUA e India**, no China ni Turquía. Las otras dos fracciones que cubre
(7305.12.91 y 7305.19.99) también aparecen en el corpus, pero declaradas
con origen `CN` y `TR` respectivamente — países que esta resolución NO
menciona. No hay evidencia (todavía) de que esas dos combinaciones
(`CN`+`7305.12.91`, `TR`+`7305.19.99`) tengan una cuota propia bajo otra
resolución — **no se afirma que la tengan ni que no la tengan**: queda
`NEEDS_VALIDATION`, no asumido en ningún sentido.

## Un cruce verificado que NO aplica — por fecha, no por producto

`CN` + `6911.10.01`/`6912.00.99` (vajillas y piezas sueltas de cerámica y
porcelana) tuvo cuota compensatoria desde 2014 (precio de referencia 2.61
USD/kg), pero la Secretaría de Economía **la eliminó** por resolución
publicada el 2026-02-26 — antes de que empiece la ventana del corpus
(agosto 2026). Mismo producto, mismo origen, pero **vigente cuando se
impuso, inexistente cuando operan los 16 pedimentos sintéticos**. Ejemplo
exacto de por qué la vigencia se verifica por fecha de operación, nunca
se asume del nombre del producto.

- [Se elimina la cuota compensatoria a vajillas de cerámica originarias de China — incomex.org.mx](https://incomex.org.mx/index.php/2026/02/25/elimina-cuota-compensatoria-vajillas-cercamica-china/)
- [DOF, resolución, 2026-02-26](https://www.gob.mx/cms/uploads/attachment/file/1065456/20260226_RPAd_Vajillas_y_piezas_sueltas_de_vajillas.pdf)

## Respuesta a la pregunta de Erick

**Sí.** Al menos 3 de las 21 combinaciones (origen, fracción) del corpus
tienen una cuota compensatoria real, verificada contra el DOF, vigente
durante las fechas de operación del corpus. No es el caso de tipo de
cambio (donde el campo que debía activar la conversión ya venía
pre-convertido) ni un "casi": son tres resoluciones distintas,
corroboradas cada una por más de una fuente, con montos y fechas
verificables.

Las 18 combinaciones restantes (de las 21) **no se verificaron en este
reconocimiento** — no se afirma que tengan cuota ni que no la tengan.
Antes de cualquier migración haría falta completarlas una por una contra
el DOF/SIDOF, con la misma disciplina de las tres de arriba.

## Por qué esto es más parecido a Apéndice 8 que a tipo de cambio

Tipo de cambio es una serie diaria, un solo valor por fecha, un solo
documento fuente (Banxico/DOF FIX). Cuotas compensatorias es un conjunto
abierto de resoluciones, cada una con:

- **Alcance de origen específico** (verificado arriba: la misma fracción
  puede estar cubierta para un país y no para otro — 7305.11.02/12.91/
  19.99 cubre EUA e India, no China ni Turquía, aunque las tres
  fracciones aparezcan en el corpus con los cuatro orígenes).
- **Monto por exportador**, no por país (Welspun Corp tiene su propia
  cifra; "los demás exportadores" normalmente tienen una tasa residual
  distinta, que este reconocimiento no verificó).
- **Vigencia activa**: "examen de vigencia" es un estado intermedio real
  (la cuota sigue vigente mientras se tramita, pero el resultado puede
  cambiarla, reducirla o eliminarla — como pasó con las vajillas).
- **Sin un índice único**: cada resolución es su propia publicación del
  DOF, sin un catálogo central descargable (la página de SNICE enlazada
  en el documento maestro es un portal informativo, no un buscador por
  fracción — verificado, no tiene parámetros de consulta).

## Qué propongo (para que Erick decida, no una migración todavía)

1. **Completar la verificación de las 18 combinaciones restantes** contra
   el DOF/SIDOF antes de proponer cualquier esquema — mismo criterio que
   Apéndice 8: no modelar con huecos sin llenar.
2. **Si Erick decide seguir**, el patrón más cercano sigue siendo
   `fraction_nom_requirements`/`pedimento_identifier_requirements`: clave
   natural (fracción + país de origen + exportador, cuando aplique +
   `valid_from`/`valid_to`), vigencia, procedencia, sin lógica en la
   tabla — el LLM nunca calcula el monto, sólo lo cita (regla 6 CLAUDE.md).
   La pieza nueva frente a esos dos precedentes: el campo "exportador"
   (string libre o catálogo propio, con una tasa residual para "los
   demás") — **no existe hoy en el Canonical Model** y necesita su propia
   decisión antes de migrar.
3. **Consumidor inmediato, antes de cargar nada**: `core/taxation` (el
   cálculo del valor en aduana/contribuciones) y el Espejo
   (`core/shadow/compare.py`), igual que tipo de cambio — no el RAG. Esta
   cuota SÍ es un número que entra al cálculo determinista (regla 6:
   `Decimal`, nunca `float`, el LLM sólo explica el resultado ya
   calculado), a diferencia de Apéndice 8, que es prosa para citar.

## Pendiente de tu decisión

- ¿Completo la verificación de las 18 combinaciones restantes antes de
  proponer el esquema, o prefieres acotar el alcance a las 3 ya
  confirmadas (o a una de ellas) para una primera carga pequeña?
- ¿Abro ya la decisión del campo "exportador" (string libre vs catálogo
  propio vs sólo tasa residual "los demás"), o la dejas para cuando
  tengamos las 21 combinaciones verificadas?
