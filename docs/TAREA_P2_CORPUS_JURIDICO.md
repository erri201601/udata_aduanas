# Tarea Persona 2 — El corpus jurídico y los catálogos vacíos

> Estado verificado el 8 de septiembre de 2026, 15:20, contra `develop` (e68683b)
> y la base compartida (alembic `4f2e5479db69`).

Brandon: **eres el camino crítico del proyecto.** No es una forma de hablar. Lo
que te toca desbloquea a las tres personas a la vez, y hasta que exista, el
resto del sistema corre y responde «no pude comprobarlo».

## Por qué

`regulatory.legal_rules` tiene **0 filas**. La cadena es literal:

```
sin corpus  →  no hay evidencia LEGAL_SOURCE
            →  el contrato de evidencia bloquea toda clasificación
            →  el Pedimento Espejo no puede comparar fracciones
            →  no aparece un peso
```

Lo comprobé corriendo `POST /pedimentos/{id}/review` contra el pedimento real:
`201 Created`, revisión persistida, y en la respuesta *«3 puntos quedaron sin
comprobar»*. El motor está bien; le falta materia prima.

---

## Tarea 1 — Cargar los catálogos que ya construiste (rápido)

Tu PR #44 creó las cuatro tablas y el cargador. **Las tablas están vacías.** Ya
apliqué tu migración a la base compartida, así que solo falta ejecutar:

```bash
python -m ingestion.dof.cli --target shared
```

Verifica después:

```sql
select count(*) from regulatory.customs_offices;
select count(*) from regulatory.units_of_measure;
select count(*) from regulatory.pedimento_claves;
select count(*) from regulatory.non_tariff_regulations;
```

Si el cargador necesita el RAW antes, `--raw-only` primero. Regla 7: nada se
parsea sin que el crudo esté en MinIO con su `content_hash`.

---

## Tarea 2 — El corpus jurídico (LO IMPORTANTE)

Cargar en `regulatory.legal_rules`:

1. **Notas de sección y de capítulo de la LIGIE** — empieza por aquí
2. **Ley Aduanera**
3. **RGCE 2026**

### Por qué las notas de capítulo van primero

Son lo que distingue 8471 de 8528 para una computadora portátil. Hoy el motor
no puede separarlas: RGI 1 devuelve las dos como candidatas, RGI 3 a) no
discrimina, y cae a RGI 3 c) —«la última en orden numérico»— que elige 8528.
La regla se aplica bien; lo que falta es la nota que excluye.

Son además el volumen más pequeño de los tres y el que más desbloquea.

### El contrato que te fijó Persona 3 en el PR #45

**`valid_from` y `valid_to` por CHUNK, no por documento.** No es preferencia
suya, es la regla 5:

La Ley Aduanera como documento tiene una fecha de publicación, pero el artículo
36-A se reformó en una fecha y el artículo 1 viene de 1995. Si la vigencia es
por documento, preguntar «qué regía el 15-03-2024» devuelve el documento entero
en su última versión, y citarías un texto de artículo que ese día no existía.

Su parser ya reconoce `(Reformado … DOF el 25-06-2018)`, que es de donde sale
la fecha de **ese** texto. Aprovéchalo.

### Lo demás que no es negociable

| | |
|---|---|
| `data_origin` | `OFFICIAL` para lo del DOF. Nunca `SYNTHETIC` para texto real. |
| RAW primero | A MinIO con `content_hash` **antes** de parsear (regla 7). |
| `valid_to = NULL` | Significa vigente. Nunca se inventa una fecha de fin. |
| `TIMESTAMPTZ` | Una fecha del DOF sin zona horaria es ambigua. |
| Migraciones | Las creas tú con Alembic; a la base compartida las aplico yo. |

### Aviso sobre el fixture de Persona 3

`tests/fixtures/ley_aduanera_fragmento.txt` **reproduce la estructura del DOF
pero su texto no está verificado**, y por eso sale `SYNTHETIC`. Sirve para
probar el parser, no para cargar. Descarga el texto real, con su URL y su
`content_hash`.

Desde el PR #43, una norma con `data_origin='SYNTHETIC'` **no puede fundamentar
jurídicamente**: el contrato lanza `SyntheticLegalBasisError`. Si cargas el
fixture por error, no romperás nada en silencio — pero tampoco desbloquearás
nada.

---

## Tarea 3 — Ground Truth y generador sintético (§24, §26)

Después del corpus. Es lo que permite decir **con qué precisión** clasifica, no
solo que clasifica.

Importa más de lo que parece: los 508 tests prueban el motor contra los casos
que nosotros escribimos, no contra verdad conocida. Sin Ground Truth, cuando
alguien pregunte «¿qué tan bien funciona?», la respuesta honesta es «no lo
sabemos».

La tabla `intelligence.ground_truth_records` ya existe.

---

## Después (no ahora)

- **Anexo 2.2.1 del Acuerdo de la SE** — la correlación fracción → NOM que
  verificaste que NO está en el Anexo 22. Es fuente aparte: otro emisor
  (Secretaría de Economía, no SHCP), otro instrumento, vigencia propia.
- **Resto de la tarifa** — hoy hay 2 capítulos de 97.
- **Las nueve fuentes restantes** — PROSEC, Regla 8ª, NOM, cuotas
  compensatorias, Banxico, ANAM, SAT, CBP CROSS, EBTI.

---

## Definition of Done

Tests, type hints, logs estructurados, manejo explícito de error, migración si
toca el esquema, trazabilidad de fuentes, sintéticos marcados, sin secretos.

Un PR por tarea, contra `develop`. Reporta con el formato del §46.

Antes de reportar estado: `git fetch --prune && gh pr list`.
