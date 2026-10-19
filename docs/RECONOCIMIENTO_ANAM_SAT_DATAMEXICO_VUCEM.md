# Reconocimiento — ANAM, SAT Datos Abiertos, Data México y VUCEM (§11)

> Sin migración ni carga nueva. Verificación de acceso real a las 4
> fuentes de menor prioridad del §11 (tarea 5, "luego" de CBP/EBTI —
> sesión del 13-oct-2026). Alcance deliberadamente más ligero que
> `RECONOCIMIENTO_CBP_CROSS_EBTI.md`: el maestro las marca como uso de
> **calibración/benchmarks**, no como fuente de fundamento jurídico.

## ANAM — las 3 URLs del §11 ya no existen

Verificado en vivo, 13-oct-2026: las tres URLs que cita el maestro
devuelven **HTTP 410 Gone**:

- `https://www.anam.gob.mx/estadisticas-anam/`
- `https://www.anam.gob.mx/operaciones-pedimentos-y-valor-de-las-mercancias/`
- `https://www.anam.gob.mx/informe-mensual/`

El sitio de ANAM se reorganizó. Lo que hoy existe en su lugar, navegando
desde `anam.gob.mx`: **las herramientas de estadística de comercio
exterior ya no viven en ANAM — viven en VUCEM** (ver abajo) y un enlace
directo al portal nacional de datos abiertos, `https://datos.gob.mx/`.
Esto no es una carga pendiente: es una corrección al maestro para que
nadie más intente estas 3 URLs esperando que funcionen.

## VUCEM — sí publica un archivo real, aún sin verificar su granularidad

`https://www.ventanillaunica.gob.mx/vucem/cifras.html` (que ANAM ahora
referencia como su propia sección de estadísticas) ofrece una descarga
real: **`Informacion_estadistica_publica_de_comercio_exterior.xls`**, con
su propio diccionario de datos (`Diccionario de datos - Informacion
estadistica publica de comercio exter....xlsx`). No descargué ninguno de
los dos: antes de proponer un parser hay que confirmar si el nivel de
detalle es por fracción arancelaria o sólo agregado nacional/sectorial —
la propia página no lo dice. Primer paso real de una carga futura:
descargar y abrir estos dos archivos, no asumir su estructura.

## SAT Datos Abiertos — dos reportes reales de pedimentos, sin fracción

`https://www.sat.gob.mx/minisitio/DatosAbiertos/dyp.html` publica, entre
otros, **`FORMATO_43_ImpNum.xls`** (pedimentos de importación) y
**`FORMATO_44_ExpNum.xls`** (pedimentos de exportación) — conteos de
pedimentos, no desagregados por fracción según el propio nombre del
archivo ("Núm." = número/conteo). Útil para "calibración estadística"
(§11: *"calibración estadística, synthetic generator"*) — por ejemplo,
validar que el NÚMERO de pedimentos por aduana/periodo que genera
`synthetic/` no esté en un orden de magnitud absurdo — pero no para
clasificar ni para auditar una partida concreta.

## Data México — API real, pero el dominio no resuelve hoy

El maestro cita `https://www.economia.gob.mx/datamexico/es/about/infoapi`,
que es informativa. La API real documentada (confirmada por búsqueda,
Datawheel/Tesseract OLAP, patrón `https://api.datamexico.org/tesseract/
data.jsonrecords?cube=...&drilldowns=...&measures=...`) **no resuelve
hoy** — `getaddrinfo ENOTFOUND api.datamexico.org`, probado dos veces por
dos canales distintos (`httpx` directo y `WebFetch`), 13-oct-2026. No se
puede distinguir desde aquí si el dominio cambió, está caído, o es un
bloqueo de red de este entorno — lo que sí se puede afirmar es que hoy
no hay nada que verificar de primera mano. Queda `SOURCE_NOT_AVAILABLE`,
no se inventa su estructura.

## Qué propongo

1. **Corregir las 3 URLs de ANAM** en el maestro (§11) la próxima vez que
   alguien lo edite — apuntan a páginas muertas desde hoy.
2. **VUCEM**: descargar los dos archivos reales (`.xls`+diccionario) y
   abrir un reconocimiento aparte SÓLO si el diccionario confirma
   desagregación por fracción — si es agregado nacional, no hay nada que
   cruzar con el corpus y no vale la pena cargarlo todavía.
3. **SAT**: mismo criterio — son conteos, no catálogo. Sólo tiene sentido
   cargarlos cuando alguien necesite calibrar el generador sintético
   contra volumen real, no antes.
4. **Data México**: reintentar cuando el dominio resuelva; no se puede
   avanzar más sin acceso real.

## Decisión de Persona 1

Pendiente -- este documento es el reconocimiento, no la carga.
