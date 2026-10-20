# ADR 0015 — El folio de una decisión: `AD-AAAA-NNNNNN` (§17)

- **Fecha:** 2026-10-20
- **Estado:** aceptado (2026-10-20, por delegación de Persona 1)
- **Decide:** Persona 1, que delega lo técnico; queda escrito aquí.
- **Pide:** §17 del maestro, que identifica cada decisión como
  `Decision ID AD-2026-000001`.

## Contexto

Todo lo demás que pide §17 ya existía: clasificación, confianza, RGI aplicadas,
fuentes, documentos, modelo, versión de prompt y de motor, hashes y revisión
humana (`classification_decisions` + `evidence_records`). Lo único que faltaba
era el identificador legible. Un UUID no se dicta por teléfono ni se cita en un
dictamen o en un correo al cliente; un folio sí.

## Decisión

1. **Columna `classification_decisions.folio`**, `NOT NULL UNIQUE`. El UUID
   sigue siendo la clave y todas las FK apuntan a él; el folio es para
   personas.
2. **Lo asigna la base**, nunca Python: `DEFAULT
   intelligence.siguiente_folio_de_decision()`, que toma `nextval` de una
   secuencia. Dos escrituras concurrentes no pueden chocar, y ninguna ruta de
   código —la API, una CLI, un script de César— puede olvidarse de ponerlo.
3. **El año es el de emisión en la Ciudad de México**
   (`now() AT TIME ZONE 'America/Mexico_City'`), no el de la sesión. Con el
   `TimeZone` del cliente, una decisión emitida la Nochevieja cambiaría de año
   según quién la escribiera.
4. **Una sola secuencia, no una por año.** El número no vuelve a 1 cada enero:
   en 2027 los folios seguirán desde donde quedaron (`AD-2027-006412`…). Una
   secuencia por año exige una tabla de contadores con bloqueo. Lo que importa
   es que no se repita y que crezca, y eso lo da una sola. Si un día hace falta
   la numeración anual, se cambia la función y no se toca ningún dato.
5. **Huecos aceptados.** Una transacción que se revierte consume un número
   (las secuencias no se revierten). Un folio saltado no es un folio repetido;
   los tests lo dan por hecho.
6. **Ancho mínimo 6, no fijo.** `lpad` recorta lo que pasa del ancho: con 6
   fijos, la decisión 1 000 000 saldría con el folio de la 100 000. El ancho
   crece con el número.
7. **Las decisiones existentes** reciben folio en orden de `created_at`, con el
   año en que se emitieron, y la secuencia queda en el siguiente.

## Dónde se ve

- `GET /classifications` y `GET /classifications/{id}` devuelven `folio`. El
  listado acepta `?folio=AD-2026-000123`, normalizado (espacios, minúsculas).
- El dictamen de una decisión y el dossier §49 llevan el suyo.
- Consola, pantalla Classification: «Decisión `AD-…`» sobre el veredicto, y el
  folio del dictamen en su pie.

## Consecuencias

- No hay contrato roto: el campo es nuevo y de sólo lectura.
- Un veredicto humano es también una decisión y tiene su propio folio. Cuando
  César cite «el dictamen AD-2026-005931», eso lleva a su veredicto, y el
  veredicto apunta a la decisión que revisó.
