# Reconocimiento — CBP CROSS y EBTI (§11, §19 maestro)

> Sin migración ni carga nueva. Sólo verificación de acceso real a las dos
> fuentes, como pidió Persona 1 (tarea 5 de la sesión del 13-oct-2026,
> "CBP CROSS y EBTI primero").

## La advertencia del maestro, primero

§11 lo dice en las dos fuentes: *"No convertir automáticamente HTS10 a
TIGIE"* (CBP CROSS) y *"No convertir CN/TARIC directamente a clasificación
mexicana"* (EBTI). Son **casos comparables** (§19: "comparable cases" como
entrada a la clasificación), nunca fundamento jurídico mexicano — ese
distingo ya está en el propio enum `EVIDENCE_KIND` (`COMPARABLE`,
`database/models/enums.py:104-109`), con el comentario explícito de por
qué existe aparte de `LEGAL_SOURCE`.

## Hallazgo que cambia la pregunta: no falta tabla, falta catálogo

Antes de proponer un esquema nuevo, verifiqué si `EvidenceRecord` ya
puede citar un caso comparable sin tabla propia. **Sí puede:**
`EvidenceRecord.evidence_kind` ya acepta `"COMPARABLE"`
(`intelligence.py:98-99`) y `document_refs` (JSONB,
`[{document, article, url, published_at, content_hash}, ...]`,
`intelligence.py:72-73`) ya es genérico para citar cualquier documento
externo — un ruling de CBP o una BTI de la UE encajan sin cambiar una
columna: `document="CBP HQ H340257"`, `url="https://rulings.cbp.gov/ruling/h340257"`,
`evidence_kind="COMPARABLE"`.

**No hace falta un `ComparableCase` nuevo para CITAR un caso ya
encontrado.** Lo que falta es un CATÁLOGO del que sacar cuáles casos
existen para una mercancía dada — y ahí es donde las dos fuentes reales
se complican.

## CBP CROSS — verificado en vivo, 13-oct-2026

`https://rulings.cbp.gov/` es una aplicación de una sola página (SPA):
tanto la búsqueda (`/search`) como una resolución individual
(confirmado con una URL real, `https://rulings.cbp.gov/ruling/h340257`)
devuelven, por HTTP simple, sólo el esqueleto de navegación del sitio —
el contenido real (número, fecha, HTS, texto) lo pinta JavaScript
después de cargar. **No hay API pública ni descarga masiva documentada
por el propio CBP** (confirmado contra `catalog.data.gov` y la página de
ayuda de CROSS): sólo scrapers de terceros (ej. un servicio de pago en
Apify), que no es algo que se deba contratar sin que Persona 1 lo decida
— y que de cualquier forma no resuelve el problema de fondo (ver abajo).

CROSS sí confirma su propio tamaño: *"última actualización 13-oct-2026,
9:51 AM con 1 ruling, llevando el total de resoluciones buscables a
222,009"* — una base viva, de cientos de miles de resoluciones, no un
catálogo que tenga sentido traer completo.

## EBTI — verificado en vivo, 13-oct-2026

La URL del §11 (`taxation-customs.ec.europa.eu/.../european-binding-tariff-information-ebti_en`)
es informativa, sin buscador. Remite a
`https://ec.europa.eu/taxation_customs/dds2/ebti/ebti_home.jsp`, que a su
vez remite a la plataforma real:
`https://webgate.ec.europa.eu/class-public-ui-web/#/search` — el `#/` en
la URL ya es la misma señal que CROSS: otra SPA (Angular/React con
ruteo por hash), sin formulario HTML nativo ni API pública documentada.
Mismo resultado que CBP: no hay nada que un `httpx.get()` pueda leer.

## Por qué NO propongo un scraper hoy

1. **Las dos requieren un navegador con JavaScript** (Playwright/Selenium)
   para ver un solo resultado — ninguna otra fuente de este repo necesita
   eso hoy (`ingestion/*` es `httpx` + `pdftotext`/HTML estático). Añadir
   ese tipo de dependencia es una decisión de infraestructura, no algo
   que se deba colar en una tarea de reconocimiento —
   `ARCHITECTURE_DECISION_REQUIRED` si Persona 1 lo quiere.
2. **El volumen no pide scraper.** §19 usa "casos comparables" como
   evidencia de apoyo puntual para una clasificación difícil, no como un
   catálogo que se consulta masivamente — el mismo patrón que ya eligió
   este equipo para cuotas compensatorias: una resolución a la vez,
   verificada a mano contra el documento primario
   (`ingestion/se/cuotas_compensatorias.py`), no un crawl completo.
3. **`EvidenceRecord` ya tiene dónde poner el resultado, y ya hay quien lo
   lee.** Verificado en `apps/api/routers/evidence.py::_a_evidence`
   (líneas 113-134): lee `fila.evidence_kind` y `fila.document_refs` de
   cada `EvidenceRecord` y los convierte en la `Evidence` del dossier del
   §49 -- el mismo camino que hoy ya usa `LEGAL_SOURCE`/`HUMAN` serviría
   sin cambios para `COMPARABLE`. No hay ninguna fila sin consumidor
   posible si HOY mismo un clasificador cita a mano un ruling real que
   encontró en su propio navegador.

## Qué propongo (para que Erick decida)

1. **Nada que cargar hoy.** El camino que ya funciona —un clasificador
   cita a mano un ruling/BTI real que localizó, con su URL y fecha, como
   `EvidenceRecord(evidence_kind="COMPARABLE")`— no está bloqueado por
   nada de este reconocimiento.
2. **Si Persona 1 quiere automatizar la búsqueda** (no la carga masiva,
   sino "dado este HS6, tráeme 3 rulings parecidos"), la pregunta de
   infraestructura es si vale la pena un navegador headless en
   `ingestion/` sólo para esto, o si un servicio de terceros (de pago) es
   más barato que mantenerlo — ninguna de las dos se decide en un
   reconocimiento.
3. **ANAM, SAT Datos Abiertos, Data México y VUCEM** (siguiente orden del
   §11) quedan fuera de este documento — Persona 1 pidió CBP/EBTI
   primero; no se abrieron las demás sin que lo pida.
4. **WCO**: confirmado que no se tocó nada — contenido con licencia,
   `LICENSE_REVIEW_REQUIRED` tal cual dice el maestro, cero scraping.

## Decisión de Persona 1

Pendiente -- este documento es el reconocimiento, no la carga.
