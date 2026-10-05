# ADR 0006 — Cómo se agrega el dinero de una partida

- **Fecha:** 2026-10-05
- **Estado:** aceptado (2026-10-05)
- **Decide:** delegado. Persona 1: «decide tú lo que más convenga, yo no puedo
  decidir». Queda escrito aquí para que se pueda revocar con una lectura.
- **Validado contra:** las mutaciones sembradas del corpus, al céntimo

## Contexto

### El dinero que estaba delante y no se contaba

De los hallazgos de las revisiones vigentes, **44 traían los dos importes
dentro y salían en la consola como «sin monto»**:

```
IGI_RATE_MISMATCH   igi_amount   declarado 4 822.95   esperado 14 468.85
```

Son 9 645.90 pesos de IGI omitidos, escritos en la misma fila, y la pantalla
decía «se puede investigar, no presentar». En total: **112 257.94 omitidos** y
27 538.49 pagados de más.

### Por qué no se contaban

El monto lo ponía el motor fiscal, y el motor fiscal exige
`expected_rates` — que exige una fracción esperada que el motor pueda
sostener. Con la cobertura de clasificación en 19.84 %, tres de cada cuatro
partidas no tienen esa fracción, así que no tenían monto **aunque el error no
tuviera nada que ver con clasificar**.

### Pero un IGI mal calculado no necesita clasificar

`_espejo_documental` lo dice en su propio nombre: «lo que se puede esperar SIN
clasificar». El IGI esperado sale de `valor × tasa de la fracción DECLARADA`.
Así que el hallazgo compara lo que el importador escribió contra lo que la ley
da para la fracción que él mismo eligió. Eso es exacto y no depende de nada.

**Comprobado contra las seis mutaciones sembradas de `igi_rate`:**

```
linea  tasa orig  tasa mut  valor aduana   delta hallazgo  delta sembrado
2      0.25       0.15      106 409.90          10 641.00       10 640.99  OK
2      0.15       0.05       96 458.99           9 645.90        9 645.90  OK
2      0.35       0.25       27 670.06           2 767.00        2 767.01  OK
8      0.35       0.25        4 694.40             469.44          469.44  OK
8      0.35       0.25      195 359.32          19 535.93       19 535.93  OK
8      0.15       0.05       15 277.65           1 527.77        1 527.77  OK
```

El delta del hallazgo coincide al céntimo con
`(tasa original − tasa mutada) × valor en aduana` en las seis. No es una
estimación.

## Decisión

### 1. Dos clases de monto, y el dato dice cuál es

`risk_findings.impact_scope`:

| alcance | qué es | cómo se agrega |
|---|---|---|
| `LINEA_COMPLETA` | el delta entero de la partida (fracción, valor, origen) | se toma **uno** |
| `UNA_CONTRIBUCION` | el error de cálculo de una contribución (IGI, IVA) | se **suman** |

Una fracción mal, un valor mal y un origen mal explican **la misma**
diferencia y cada uno la lleva completa a propósito —repartirla daría cifras
que no cuadran con nada—, así que sumar dos contaría el mismo dinero dos
veces. Un IGI mal calculado y un IVA mal calculado son **contribuciones
distintas** y se deben las dos; deduplicarlas perdería una.

`NULL` = `LINEA_COMPLETA`, que es lo que eran las filas anteriores: el único
tipo que llegaba a llevar monto era la fracción.

### 2. El error de cálculo no se afirma si la base está en disputa

**Aquí se equivocó dos veces y las dos las cazó una comprobación.** Vale la
pena dejarlas escritas, porque el razonamiento intermedio parecía sólido.

#### Intento 1 — sumar las dos clases. Lo tumbó un test.

Parecía que telescopaban:

```
error de cálculo   = valor × tasa_declarada − IGI_escrito
movimiento de tasa = valor × tasa_correcta  − valor × tasa_declarada
───────────────────────────────────────────────────────────────────
suma               = valor × tasa_correcta  − IGI_escrito
```

Telescopan — **pero sólo contribución por contribución**. El delta de la
fracción no mide una contribución: mide el movimiento de **todas a la vez**, y
lo mide desde los importes **recalculados**, no desde los escritos.

Con valor 100 000, tasa declarada 0.05, correcta 0.15, IGI escrito 1 000 e IVA
escrito 18 528:

```
suma de las dos clases .... 15 600
lo que realmente se debe .. 13 872
```

El delta de la fracción ya traía dentro el arrastre del IVA (16 800 → 18 400)
medido contra un IVA que nadie escribió, y el escrito estaba 128 por encima.

#### Intento 2 — dar precedencia al error de cálculo. Lo tumbó la base real.

Si no se suman, parecía razonable que mandara el exacto. La validación contra
la base dijo lo contrario. **Línea 9 del pedimento 600002:**

```
IGI       −20 952.72
IVA        −3 352.44
fracción  +24 305.14
          ─────────────
regla:    −24 305.16  de «sobrepago»
```

Ese importador **escribió el dinero correcto bajo un código equivocado**. La
regla le decía «puedes recuperar 24 305 pesos» y no puede recuperar nada.

Y eso es peor que reportar de menos. Un número corto se corrige en una
revisión; una devolución prometida se cobra.

#### La decisión

**El error de cálculo no se afirma cuando alguna causa está abierta.**

Es `valor declarado × tasa de la fracción declarada − importe escrito`, y las
tres divergencias cuantificables atacan justamente esas dos entradas: la
fracción cambia la tasa, el valor cambia la base, el origen puede cambiar la
preferencia. Si cualquiera está en duda, el número contra el que se mediría es
el que el propio sistema acaba de poner en duda.

Efecto de paso: las dos clases quedan **mutuamente excluyentes por
construcción**, así que la pregunta «¿se suman?» ya no se puede dar. La
precedencia de `total_por_partida` se mantiene de todas formas, porque las
filas anteriores a esto sí pueden traer las dos.

Lo que se reporta en esa partida es el delta de la fracción, etiquetado como lo
que es: «se movería 24 305.14 si esto se corrigiera».

### 3. Una sola función agrega

`core.audit.total_por_partida`. El criterio vivía como una lista de tipos
repetida en tres lectores —el motor, el Espejo y el tablero— y cada copia podía
derivar de las otras sin que nada fallara: el mismo pedimento habría dado tres
cifras distintas, defendibles por separado.

Recibe pares `(importe, alcance)` y no hallazgos, porque el Espejo y el tablero
agregan filas de `risk_findings` —que no guardan la dirección, la deducen del
signo— y fabricar un objeto falso para satisfacer una firma es inventar
estructura.

El tablero lo hace en SQL porque agrega sobre la base, y hay un test que
compara **la consulta contra la función**, no contra una cadena escrita a mano.

## Consecuencias

### Lo que se gana

44 hallazgos pasan de «sin monto» a cuantificados, con importe exacto y sin
depender de clasificar. Son los que el §26 ya detecta al 100 % —tasa de IGI,
importe de IVA— y que hasta hoy no se podían presentar como dinero.

### Lo que NO se arregla, y es la frontera de esta decisión

En una partida donde la fracción está mal, el dinero que se reporta es el delta
de la fracción —condicionado— y el error de cálculo no se reporta en absoluto.
Si además el importe escrito está mal, ese error queda sin cuantificar.

Para darlo haría falta que `_fiscal_esperado` usara la tasa de la fracción
**esperada** cuando el motor la sostenga. Pero entonces `IGI_RATE_MISMATCH`
dejaría de significar «miscalculaste» para significar «miscalculaste o
clasificaste mal», que son dos acusaciones distintas contra un agente aduanal,
y el hallazgo perdería la propiedad que lo hace valioso: ser exacto sin
depender de clasificar.

Eso es otra decisión y no se toma aquí. Hoy afecta a 9 de 60 partidas con
hallazgos.

### La regla que se mantiene

Ningún total suma dos importes que midan la misma cosa, y ninguno mezcla dos
bases. Cuando hay duda entre dos cifras, se da la que se puede defender sin
clasificar.
