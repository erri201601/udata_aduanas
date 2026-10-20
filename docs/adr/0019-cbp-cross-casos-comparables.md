# ADR 0019 — CBP CROSS: casos comparables, nunca fundamento

- **Fecha:** 2026-10-20
- **Estado:** aceptado (2026-10-20, por delegación de Persona 1)
- **Decide:** Persona 1, que delega lo técnico; queda escrito aquí.

## Contexto

El maestro (§11) pide CBP CROSS como «casos internacionales comparables:
producto → HS6 → razonamiento», con una condición: «No convertir
automáticamente HTS10 a TIGIE». El §19 pone «comparable cases» entre las
entradas del Classification Engine. En el scorecard (§44), «CBP» estaba en cero.

`rulings.cbp.gov` tiene una API JSON pública:

- **`/api/search`** busca por palabra. «7615» encuentra resultados, pero
  «7615.10» no, porque los puntos parten el término.
- **`/api/ruling/{n}`** devuelve la resolución entera: texto, fecha, asunto,
  códigos HTSUS y qué la revoca o modifica.

Las resoluciones son obra del gobierno de EE. UU., de dominio público.

## Decisión

1. **Tabla propia `regulatory.comparable_rulings`, separada de
   `legal_chunks`.** Una resolución de CBP dice cómo clasificó EE. UU. en SU
   arancel. Sirve para ver qué se consideró y cómo se razonó, pero nunca
   fundamenta una fracción mexicana. Separarla impide que el RAG jurídico (y
   el Copilot) la citen como ley. Está pensada para recibir también EBTI
   (`authority`).
2. **No se convierte HTS a TIGIE.** `tariff_codes` guarda los códigos tal como
   los escribe CBP. Sólo `hs6_codes` (los seis dígitos del Sistema
   Armonizado, comunes a los dos países) se compara con México. Los capítulos
   98 y 99 son disposiciones nacionales de EE. UU. y no dan HS6.
3. **`data_origin = PUBLIC`.** Es pública, pero no oficial en México.
   `valid_from` es la fecha de la resolución.
4. **Las revocadas se conservan, marcadas** (`is_revoked`, `revoked_by`): saber
   que CBP abandonó un criterio también informa. Al recargar se actualiza el
   estado; el texto de una resolución emitida no cambia.
5. **RAW por resolución**, con clave direccionada por contenido
   (`cbp_cross/{colección}/{número}_{sha16}.json`). Se guarda la URL pública
   (`rulings.cbp.gov/ruling/{n}`), no la de descarga, que es un enlace firmado
   de S3 que caduca a los 15 minutos.
6. **Alcance: las partidas del corpus**
   (`python -m ingestion.cbp_cross.cli --target local --desde-corpus`). Se
   busca por partida (4 dígitos), se recorren todas las páginas y se queda lo
   que cita un código de esa partida. Al 20-oct: unas 220 resoluciones de
   ocho partidas, de 1988 a 2026. No se descarga todo CROSS: lo que no se
   consulta no se carga (lección del FIX).
7. **Servicio público, sin martillarlo:** 0.4 s entre peticiones.

## Límites

- **La búsqueda de CROSS es por texto.** Una resolución que cita la fracción
  sólo en un formato que la búsqueda no tokeniza puede quedar fuera. Lo que
  se carga es «lo que CROSS devuelve al buscar la partida», no «todas las
  resoluciones de la partida».
- **Nada consume todavía esta tabla.** Mostrar «qué decidió CBP para esta
  subpartida» junto a una clasificación es el siguiente paso, en su propio
  PR. Ahí debe decir, con todas sus letras, que no es fundamento.
