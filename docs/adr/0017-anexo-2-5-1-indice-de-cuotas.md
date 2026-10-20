# ADR 0017 — El Anexo 2.5.1 como índice de cuotas compensatorias

- **Fecha:** 2026-10-20
- **Estado:** aceptado (2026-10-20, por delegación de Persona 1)
- **Decide:** Persona 1, que delega lo técnico; queda escrito aquí.
- **Sigue a:** ADR 0009. Ahí quedaron 20 combinaciones del corpus en
  `NEEDS_VALIDATION` porque no había una fuente que dijera dónde hay cuota.

## Contexto

El scorecard del maestro (§44) tenía «Cuotas» casi vacío: una sola cuota, la del
cable de acero de China, leída a mano de su resolución. El ADR 0009 decía que
no había catálogo tabular, y eso era cierto para las **tasas**. Para saber
**dónde** hay cuota, sí existe uno: el **Anexo 2.5.1** del Acuerdo de Reglas
de la SE, el mismo Acuerdo del que ya cargamos el Anexo 2.4.1 de NOM.

### Qué versión

- El PDF de SNICE (`REGLAS-ANEXO251-REGLAS_20220506`) es un **borrador**: Word
  del 6-may-2022, con la fecha de firma en blanco. No se usa.
- El Acuerdo publicado en el DOF el 9-may-2022 lo trae completo.
- El **DOF 25-nov-2022** (`codigo=5672457`) lo sustituye: su punto Único
  reforma «los Anexos 2.2.1, 2.2.2, 2.4.1 y 2.5.1». Es la versión que se carga.
- De los diez acuerdos posteriores que lista el índice de SNICE (hasta el
  28-sep-2026), **ninguno** vuelve a tocar el 2.5.1. Se descargaron todos y se
  buscó en cada uno.

### Desde cuándo

El Transitorio Primero hace que el acuerdo entre en vigor «el mismo día» que la
LIGIE del 7-jun-2022. La Cuarta Resolución de Modificaciones a las RGCE 2022
(DOF 5-dic-2022, punto SEGUNDO) fija esa fecha: «entrará en vigor el 12 de
diciembre de 2022». `valid_from = 2022-12-12`. Esto se verificó en el documento
primario, no en la prensa.

### Lo que dice el propio Acuerdo sobre su anexo

- **Regla 2.5.3:** si el anexo y la resolución discrepan, «prevalecerán estas
  últimas».
- **Regla 2.5.4:** el anexo «se actualizará cada seis meses». No se ha hecho
  desde noviembre de 2022.

## Decisión

1. **Una tabla nueva, `regulatory.compensatory_duty_listings`**, separada de
   `compensatory_duties`. Las dos responden a preguntas distintas:
   - `compensatory_duties` responde **cuánto**. Tasa numérica, leída de la
     resolución y verificada. Es lo único que entra en un cálculo de dinero.
   - `compensatory_duty_listings` responde **dónde**: producto, fracción,
     origen, exportador, la cuota **como texto** y las resoluciones que el
     anexo cita.
2. **La cuota no se convierte a número.** Viene en prosa: porcentajes, dólares
   por kilo o por tonelada, precios de referencia, «no se aplica»,
   elusiones. La regla 2.5.3 manda la resolución, y la regla 6 del proyecto
   dice que el dinero es determinista y verificado. Un número parseado de un
   anexo de 2022 sería un importe sin respaldo.
3. **Cada fila guarda `latest_resolution_date`**, la última resolución que el
   anexo cita. Quien consulte sabe lo vieja que es la referencia.
4. **Clave natural** `(fraction_code, origin_country, product_description,
   exporter_text, first_resolution_date, valid_from)`. La primera resolución
   es necesaria: la tubería sin costura de China tiene dos cuotas distintas
   sobre la misma fracción (investigaciones de 2011 y 2014, para diámetros
   distintos).
5. **Países:** un diccionario cerrado de 18 nombres a ISO-2. Un país que no
   esté detiene la carga: adivinar un origen es inventar a quién se le cobra.
   «COREA» es la República de Corea, que es como la nombran las resoluciones.
6. **RAW direccionado por contenido**
   (`se/anexo_2_5_1_20221125_{sha16}.html`). El HTML del DOF cambia entre
   descargas por la barra lateral del tipo de cambio (ADR 0009), así que cada
   captura queda como objeto propio (#265).

## Resultado de la lectura

447 filas: 53 productos, 127 fracciones y 18 orígenes. Las 127 fracciones
existen en la LIGIE cargada, tanto el 2022-12-12 como hoy.

Contrastes con lo que ya sabíamos:

- **Coincide:** cable de acero de China, 2.58 USD/kg, igual que la resolución
  verificada del ADR 0009.
- **Destraba un `NEEDS_VALIDATION` del ADR 0009:** la tubería 7305 de India
  aparece como «WELSPUN CORP LTD. Y TODAS LAS DEMÁS EXPORTADORAS», 128.24
  USD/t. El exportador del corpus (BHARAT) entra en «todas las demás». Falta
  leer la resolución vigente para la tasa.
- **Toca mercancía del corpus:** olla de presión de aluminio de China
  (7615.10.02), 92.64 %.
- **Muestra la foto vieja:** vajillas de China (6911.10.01 y 6912.00.99) siguen
  en el anexo, pero esa cuota se eliminó en 2026
  (`docs/RECONOCIMIENTO_CUOTAS_COMPENSATORIAS.md`). Por eso el anexo es un
  índice y no una tarifa.

## Lo que no se hace aquí

- **El Espejo no lo usa todavía.** Señalar «posible cuota compensatoria, sin
  importe» es una regla de detección y se mide sola, contra el ground truth,
  en su propio PR («una regla por vez»).
- **Las 156 resoluciones de prácticas desleales** que lista el índice de SNICE
  (2020–2026) son el camino para actualizar esta foto y para cargar tasas
  verificadas. Queda como siguiente paso.

## Hallazgos de paso (deuda, fuera de alcance)

- **NOM:** `fraction_nom_requirements` está cargada con el Anexo 2.4.1 del
  16-may-2022, sin fecha de fin. El mismo acuerdo del 25-nov-2022 lo
  sustituyó, en vigor desde el 12-dic-2022. Hay que cargar esa versión y cerrar
  la anterior.
- **LIGIE 2022:** `tariff_fractions` usa como `valid_from` el 2022-06-07, que
  es la publicación. La entrada en vigor fue el 2022-12-12. No afecta al corpus
  (2024–2026), pero rompe la regla 5 para operaciones de junio a diciembre de
  2022.
