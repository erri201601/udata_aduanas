# Reconocimiento — RGCE 2026 (Tarea 2, Persona 2)

> Sin cargar nada. Sólo RAW capturado + análisis de estructura, como pidió
> Persona 1 antes de decidir el corte de PRs. 2026-09-09.

## Fuente

```
https://dof.gob.mx/nota_detalle_popup.php?codigo=5777199
```

(la misma URL de `docs/00_ADUANERO_OS_PROMPT_MAESTRO.md`, sección "RGCE 2026").

- **RAW capturado** a MinIO local: `dof/rgce_2026_reconocimiento.html`
- **content_hash**: `272346ff5e9f18eb267348a9d54813c80b9b4d162107306b0e55aaa4ac37eaaa`
- **Tamaño**: 5,082,614 bytes (HTML, no PDF — el DOF publica esta nota como
  HTML completo, igual que la LIGIE vía `ligie_2022.htm`)
- Firmada en Ciudad de México, **17 de diciembre de 2025**.

No se tocó la base compartida ni la local: esto es sólo RAW + lectura.

## Estructura

| | |
|---|---|
| Títulos | 7 |
| Capítulos | 90 |
| Reglas (patrón `N.N.N.`, p. ej. `1.1.1.`) | **550**, sin duplicados |
| Fracciones romanas dentro de reglas | ~1,476 |
| Numeración con sufijo de letra o "bis" | Ninguna encontrada |

La numeración es decimal (Título.Capítulo.Regla), nada que ver con el
`ARTICULO N` de la Ley Aduanera.

## Vigencia: NO es el mismo problema que la Ley Aduanera — es uno distinto

**No hay notas inline** tipo `(Reformado/Adicionado/Derogado DOF ...)` en
ninguna regla. Cero coincidencias en todo el documento. Tiene sentido: esto
no es un texto consolidado con décadas de reformas incrementales como la Ley
Aduanera — es una **resolución anual completa**, reemplazada entera cada año.
Las modificaciones durante el año («Segunda Resolución de Modificaciones a
las RGCE para 2026») son publicaciones del DOF **separadas**, fuera del
alcance de este documento.

Eso simplifica el caso general: **`valid_from`/`valid_to` uniformes por
documento SÍ son correctos aquí**, y sí existen explícitos —Transitorio
Primero, textual:

> «La presente Resolución entrará en vigor el 1o. de enero de 2026 y estará
> vigente hasta el 31 de diciembre de 2026.»

`valid_from = 2026-01-01`, `valid_to = 2026-12-31`. Sin inventar nada: viene
literal del propio texto.

### Pero hay una excepción real, y es del mismo tipo de riesgo que el bug de Ulises

Los Transitorios Tercero y Cuarto declaran que **reglas específicas no
entran en vigor el 1o. de enero**:

- **Transitorio Tercero**: reglas `2.1.1.` y `4.6.1.` (más Anexos 3, 4, 25 y
  apéndices 1, 6, 21 del Anexo 22) entran en vigor el **2 de febrero de
  2026**.
- **Transitorio Cuarto**: una lista de 13 reglas/fracciones (`1.6.27.
  fracción IV`, `1.6.28.`, `1.6.37.`, `4.2.5.`, `4.2.6.`, `4.2.10.`,
  `4.2.11.`, `4.2.13.`, `4.2.14.`, `4.2.18.`, `4.2.22.`, `5.5.1.`, `7.3.1.
  fracción IV`) entran en vigor según el transitorio de OTRO decreto (el de
  reformas a la Ley Aduanera, DOF 19-11-2025) — ni siquiera traen una fecha
  propia dentro de este documento.

Si el cargador estampa `2026-01-01` a las 550 reglas por igual, esas 15
reglas quedarían con una vigencia que el propio documento contradice — el
mismo tipo de error que encontró Ulises en la Ley Aduanera, sólo que aquí la
fuente de la fecha correcta está en los Transitorios, no en una nota junto a
cada regla.

## Riesgo de anexo final (ya conocido, mismo patrón que Ley Aduanera)

Después de "Transitorios" viene "ANEXO 13 DE LAS REGLAS GENERALES..." —una
tabla de multas actualizadas—, estructuralmente igual al anexo monetario que
ya hubo que excluir en el parser de la Ley Aduanera. El corte tiene que
hacerse antes de "Transitorios", igual que allá.

## ¿Sirve el parser de la Ley Aduanera?

**No, tal cual.** Tres diferencias estructurales, no cosméticas:

1. Encabezado: `_HEADING_RE` busca `ARTICULO N[-LETRA]`; aquí es `N.N.N.`
   decimal — regex distinto de raíz.
2. Notas de vigencia: `_vigencia_de_notas()` depende de notas inline junto a
   cada artículo; aquí no existen. La vigencia por regla sale de un cruce con
   los Transitorios (dos reglas exactas + un rango de 13 más), no de líneas
   pegadas al texto.
3. El resto sí es reutilizable: filtrado de ruido de página, corte antes de
   "Transitorios", extracción de fracciones romanas (mismo patrón que ya
   usa `rag.chunking._fracciones`).

Conclusión: **parser nuevo** (`ingestion/dof/rgce.py` o similar), reutilizando
piezas sueltas, no el archivo completo.

## Corte de PRs propuesto

1. **Este PR** — sólo reconocimiento (este documento). Sin código de carga.
2. **Parser + tests**, sin cargar nada: 550 reglas parseadas contra el HTML
   real, con las 15 excepciones de vigencia de los Transitorios resueltas
   correctamente contra fragmentos reales del documento (regresión explícita
   para 2.1.1./4.6.1. y para las 13 de fracción IV/Transitorio Cuarto).
3. **Carga real** a `legal_rules` + `legal_chunks`, primero local, luego
   compartida (migración si hiciera falta — no debería, la tabla ya existe).

No veo necesidad de partir la carga en más de un PR por tamaño: 550 filas es
el doble de la Ley Aduanera (274), no un salto de orden de magnitud.

## Pendiente de tu decisión

- ¿Confirmas este corte en 3 piezas?
- ¿El alcance de esta primera carga es sólo el cuerpo de reglas (como con la
  Ley Aduanera), dejando fuera los 30 Anexos de las RGCE (cada uno es
  potencialmente su propio documento — el Anexo 22 ya se cargó aparte)?
