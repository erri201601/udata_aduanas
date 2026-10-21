# ADR 0023 — Aplicar los decretos que modifican la Tarifa

- **Fecha:** 2026-10-21
- **Estado:** aceptado (2026-10-21, por delegación de Persona 1)
- **Decide:** Persona 1, que delega lo técnico; queda escrito aquí.
- **Sigue a:** ADR 0018, cuya parte 2 proponía versionar las tasas por decreto.

## Contexto

La tarifa cargada es la foto de SNICE del 20-abr-2026. Después de esa fecha,
el decreto del DOF del 13-oct-2026 dejó exenta la 9803.00.01, que estaba al
10 %, desde el 14-oct-2026 y por cinco años. La base seguía diciendo 10 %.

## Decisión

`ingestion.dof.decretos_tarifa`:

1. **Lee la tabla del decreto** del HTML del DOF (`tablas_html`): fracción,
   descripción, unidad, IGI e IGE. Las tablas de cuatro columnas (el artículo
   5 del PROSEC, que viene en el mismo decreto del 23-abr-2026) no se mezclan.
2. **La fecha sale del transitorio** (`afectacion.vigencia_de`, ADR 0022). Si
   no es inequívoca, no se aplica nada.
3. **Sólo donde la tasa cambia:** la versión vigente se cierra el día anterior
   y se abre una nueva con las tasas del decreto. Si el decreto dura N años, la
   versión nueva acaba ahí; lo que rija después no se inventa. Idempotente.
4. **Los NICO se copian** a la versión nueva y los originales se cierran el
   mismo día, porque `nicos.tariff_fraction_id` apunta a una versión concreta.
   Sin esto, el Espejo y el clasificador se quedarían sin NICO desde esa fecha.
5. **RAW por decreto**, con el hash en la clave.

## Resultado (dry-run sobre los decretos reales)

| Decreto | Fracciones | Cambian | En vigor |
|---|---:|---:|---|
| 13-oct-2026 | 1 | 1 (9803.00.01: 10 % → Ex.) | 2026-10-14 al 2031-10-13 |
| 23-abr-2026 | 185 | 0 | 2026-04-24 |
| 29-dic-2025 | 1 463 | 0 | 2026-01-01 |

Los dos últimos coinciden con la foto **hacia adelante**. Que coincidan dice
algo de lo que pasa **hacia atrás**: esas tasas rigen desde su decreto, no
desde 2022. Eso es la parte 2 del ADR 0018, en su propio PR.

## Parte 2 — hacia atrás (21-oct)

Que un decreto **confirme** la tasa de la foto también dice algo: esa tasa rige
**desde el decreto**, no desde 2022. Antes regía otra que no tenemos cargada.

**Decisión:** con `--hacia-atras`, cada decreto parte la versión vigente en su
fecha. El tramo anterior queda con la tasa en `NULL` («no se sabe»: el Money
Finder ya lo trata como «sin monto», nunca como cero) y el tramo desde el
decreto lleva sus tasas y sus NICO. Se aplica **del decreto más reciente al
más antiguo**, así que sólo el último que toca cada fracción la parte.

**Lo que NO hace, y por qué:** llenar el tramo desconocido con un decreto más
viejo. El índice de SNICE **no está completo**: le falta, por ejemplo, el
decreto de agosto de 2023, que subió aranceles con vigencia temporal. Llenar
con un decreto anterior podría extender una tasa a un periodo en que regía
otra. Una tasa conocida que el decreto contradice es un **conflicto**: se
reporta y no se toca.

**Riesgo residual, dicho:** una fracción que modificó un decreto que no está en
el índice sigue con la tasa de la foto desde 2022. Cerrarlo exige la tarifa
original de 2022 y la lista completa de decretos sacada del DOF día por día.

**Simulación** (los 8 decretos en una transacción revertida, del más reciente
al más antiguo):

| Decreto | Desde | Fracciones | Acotadas | Ya sin tasa previa | Conflictos |
|---|---|---:|---:|---:|---:|
| 23-abr-2026 | 2026-04-24 | 185 | 185 | 0 | 0 |
| 29-dic-2025 | 2026-01-01 | 1 463 | 1 463 | 0 | 0 |
| 10-nov-2025 | 2025-11-11 | 8 | 8 | 0 | 0 |
| 19-dic-2024 | 2024-12-20 | 155 | 0 | 155 | 0 |
| 08-may-2024 | 2024-05-09 | 1 | 1 | 0 | 0 |
| 22-abr-2024 | — | — | no se aplica: transitorio no inequívoco (arancel-cupo) | | |

1 699 fracciones dejan de afirmar una tasa antes de su último decreto.
**Ninguna partida del corpus cambia de tasa**, porque todas sus operaciones son
posteriores.
