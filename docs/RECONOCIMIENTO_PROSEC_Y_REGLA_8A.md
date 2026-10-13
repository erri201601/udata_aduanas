# Reconocimiento — PROSEC y Regla 8a (§11, §23 maestro)

> Sin migración ni carga nueva. Sólo lectura del documento real + lo que
> ya está cargado, como pidió Persona 1 para PROSEC/Regla 8a (hoy, tarea
> 5 de la sesión del 13-oct-2026), al mismo estilo de
> `docs/RECONOCIMIENTO_APENDICE_8.md` y
> `docs/RECONOCIMIENTO_CUOTAS_COMPENSATORIAS.md`.

## Por qué este reconocimiento, y no una migración directa

`core/opportunity/engine.py` ya lo dice de frente: *"PROSEC, Regla 8ª y
preferencias arancelarias no se evaluaron: sus tasas son datos jurídicos
con vigencia y fuente"* — el motor espera que alguien le aporte
`preferential_rates` desde fuera, y hoy nadie lo hace porque ninguna de
las dos fuentes está cargada. `database/models/enums.py` ya tiene
`MISSED_PROSEC` en el vocabulario de `ERROR_TYPE`, sin un solo dato real
detrás.

Antes de proponer un esquema hacía falta leer los documentos primarios
reales -- no el resumen de las páginas de SNICE que el maestro cita como
fuente, que resultaron ser landing pages sin el texto (ver abajo) -- y
cruzarlos contra las 12 fichas de catálogo que ya usa el corpus sintético
(`synthetic/catalog.py`), para saber si hay algo que migrar hoy o si,
como pasó con los identificadores del Apéndice 8 el 6-oct, el corpus
real no ejercita ninguna fila estructurable todavía.

## PROSEC — documento real, no el que cita la landing page

`https://www.snice.gob.mx/cs/avi/snice/programasdefom.prosec.html` (la
URL del §11 maestro) es una página de navegación sin tablas ni
fracciones -- sólo enlaces a "Normatividad" y un correo de contacto.
**El documento primario real** (localizado y leído completo, no citado
de un resumen de prensa ni de buscador):

> **Decreto por el que se establecen diversos Programas de Promoción
> Sectorial.** Publicado en el DOF el 2 de agosto de 2002. Última reforma
> publicada DOF 22-05-2024. Texto consolidado capturado por SNICE el
> 26-08-2024: `https://www.snice.gob.mx/~oracle/SNICE_DOCS/DECRETO-PROSEC-BIBLIOTECA_20240826-20240826.pdf`
> (246 páginas, verificado con `pdftotext -layout`, 13-oct-2026).

**Dos fechas, no una** -- mismo cuidado que ya pidió el ADR 0009: la
vigencia real de la última reforma es **22-05-2024** (la que dice el
propio encabezado del decreto); **26-08-2024** es sólo cuándo SNICE
capturó esa versión a su biblioteca, no una fecha de reforma.

### Qué tiene el decreto (verificado leyendo, no asumido)

- **Artículo 3**: 24 sectores (Eléctrica, Electrónica, Mueble, Juguete,
  Calzado, Minera y Metalúrgica, Bienes de Capital, Fotográfica,
  Maquinaria Agrícola, Industrias Diversas, Química, Caucho y Plástico,
  Siderúrgica, Farmoquímicos, y más).
- **Artículo 4**: por sector, las mercancías FINALES que el productor
  autorizado puede fabricar (clasificadas por partida/subpartida/fracción
  de la TIGIE).
- **Artículo 5**: por sector, los INSUMOS que ese productor puede
  importar con el arancel preferencial (frecuentemente 0%, columna
  "Ex.") -- misma estructura de 3 columnas que el Apéndice 8
  (`CÓDIGO | DESCRIPCIÓN | ACOTACIÓN`), pero mucho más grande: cientos
  de filas, mezclando partida (2 dígitos), subpartida (6 dígitos) y
  fracción completa (8 dígitos) en la misma columna, con acotaciones
  "Excepto:"/"Únicamente:" igual de frecuentes que en el Anexo 2.4.1 de
  NOM (ADR 0003).

### Cruce real contra las 12 fichas del corpus -- el hallazgo que importa

Verificado fracción por fracción (`grep` contra las 10 fracciones reales
de `synthetic/catalog.py`, no una muestra): **4 de las 10 SÍ aparecen**
en el Artículo 5 (insumos), bajo más de un sector cada una:

| Ficha | Fracción | Aparece en PROSEC Art. 5 como |
|---|---|---|
| P002 (fregadero inox) | `7324.10.01` | "Fregaderos... y lavabos, de acero inoxidable" -- Ex. |
| P005/P006/P007 (cable de acero) | `7312.10.05` (vecina de `73121099`) | "De acero sin recubrimiento, con o sin lubricación..." -- Ex. |
| P011 (sartén inox) | `7323.93.05` | "De acero inoxidable" -- Ex. |
| P012 (estropajo acero) | `7323.10.01` | "Lana de hierro o acero; esponjas, estropajos..." -- Ex. |

**Esto NO alcanza para afirmar `MISSED_PROSEC` sobre ninguna partida del
corpus**, y por una razón que no es de datos sino de la propia condición
legal del Artículo 4: el arancel preferencial sólo aplica si (a) el
importador tiene **autorización vigente de ese Programa sectorial
específico** -- un dato que ni el Canonical Model ni el corpus modelan
hoy (no existe `Client.prosec_program` ni nada parecido) -- y (b) el
insumo se destina **a fabricar las mercancías del Artículo 4 de ESE
sector** -- un hecho de uso final, no algo que una ficha técnica declare.
Afirmar que una de estas 4 partidas "debió" usar PROSEC sin esos dos
datos sería inventar una autorización y un destino que el corpus no
tiene -- exactamente lo que `core/opportunity/engine.py` ya se negó a
hacer.

## Regla 8a — documento real, y por qué NO cruza con el corpus

`https://www.snice.gob.mx/cs/avi/snice/sectores_mx_regla8va.html` (la
URL del §11) tampoco trae el texto -- remite a:

> **Acuerdo por el que la Secretaría de Economía emite reglas y criterios
> de carácter general en materia de Comercio Exterior.** DOF 31-dic-2012
> y sus modificaciones. (Página sin PDF enlazado; sólo dos archivos Excel
> descargables -- "Fracciones de Regla 8ª" y "Desglose de autorizaciones
> 2013" -- que no abrí: el nombre y la estructura que describe la propia
> página bastan para la pregunta de este reconocimiento.)

Regla 8a cubre **25 fracciones de la partida 98.02** (`9802.00.01` a
`9802.00.25`), una para cada uno de 23 de los 24 sectores PROSEC -- es el
mecanismo para importar **maquinaria y equipo** bajo el régimen temporal
o definitivo de un Programa sectorial, reclasificándolo a una fracción
"paraguas" de la partida 98.02 en vez de su clasificación arancelaria
real.

**Las 10 fracciones reales del corpus están en los capítulos 69, 73 y
76 -- ninguna es ni puede ser una fracción 9802.00.XX.** Regla 8a no
cruza con ningún producto del catálogo actual, y no por falta de dato:
los productos del corpus (ollas, fregaderos, cable, tubería, vajillas,
sartenes, estropajos) son mercancía terminada o insumo de producción, no
maquinaria -- la categoría que Regla 8a existe para cubrir.

## Cuántos caben en una tabla simple, y cuántos no

| Categoría | Aprox. | ¿Estructurable hoy? |
|---|---:|---|
| PROSEC Art. 5, fracción coincide con una ficha del corpus | 4 de 10 | **No sin inventar**: falta `Client.prosec_program` (autorización) y el destino de uso -- ninguno de los dos existe en el Canonical Model ni en el corpus |
| PROSEC Art. 4/5, el resto (cientos de filas, sectores sin ninguna ficha del corpus) | ~95% del decreto | No es prioridad: cero fichas del corpus las ejercitan |
| Regla 8a, cualquier fracción | 0 de 10 | No aplica: espacio de fracciones (9802.00.XX) disjunto del corpus (69/73/76) |

**Ninguna fila de ninguna de las dos fuentes alimenta `MISSED_PROSEC`
hoy sin inventar un dato que ni el Canonical Model ni el corpus
tienen.** Mismo patrón que la categoría (b) del Apéndice 8
(IMMEX/decreto): el documento primario sí existe y sí se puede leer,
pero la correlación necesita un campo que hoy no está, y abrirlo sin
saber si el corpus real lo va a traer sería modelar en falso.

## Qué propongo (para que Erick decida, no una migración todavía)

1. **Cargar el Decreto PROSEC completo a RAW** (MinIO, con su
   `content_hash`) y al RAG (`regulatory.legal_chunks`) -- es tan norma
   citable como cualquier regla RGCE, y el Opportunity Finder necesita
   poder citarla aunque no pueda todavía cruzarla estructuralmente.
   Mismo criterio del ADR 0002: cargar el texto primero, la lógica de
   consumo después.
2. **NO estructurar Artículo 4/5 en una tabla fracción→sector todavía.**
   Las 4 coincidencias reales no tienen con qué activarse
   (`prosec_program`/destino de uso no existen). Si Persona 1 quiere
   abrir ese campo, es un `ARCHITECTURE_DECISION_REQUIRED` aparte -- el
   mismo que el Apéndice 8 ya dejó pendiente para IMMEX/decreto.
3. **Regla 8a: cargar sólo el nombre/fecha del Acuerdo a `legal_sources`
   si Erick quiere que exista la referencia** -- no hay tabla que
   proponer: cero cruce con el corpus actual, y los 25 fracciones de la
   partida 98.02 no tienen ninguna ficha de catálogo que las ejercite.
4. **`MISSED_PROSEC`/`MISSED_PREFERENCE` siguen sin generador ni
   detector** (ya documentado en `synthetic/README.md`, 13-oct). Este
   reconocimiento confirma que no es una carga pendiente: es que el
   corpus actual no tiene ninguna operación donde afirmarlo sin inventar.

## Decisión de Persona 1

Pendiente -- este documento es el reconocimiento, no la migración.
