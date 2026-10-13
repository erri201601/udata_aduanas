# Generador sintético (§24 maestro) — estado y plan de carga

> Rama `feature/synthetic-generator-apendice-24`. Nada de esto está
> cargado en `develop` ni en la base compartida — pendiente de que Persona
> 1 revise este plan, como pidió para toda la sesión de hoy (13-oct-2026).

## Qué es, y qué NO es

`synthetic/` no sustituye a `ingestion/sintetico/`. Produce el mismo
`dict` que ya consume `ingestion.sintetico.corpus_espejo.parse_corpus` —
es la pieza SOURCE que antes se generaba fuera del repo (un JSON subido a
mano a MinIO por Persona 1). El PARSED → DATABASE que ya existe, ya está
revisado y ya tiene 1200+ tests no se tocó: `synthetic/corpus.py` produce
un `dict`, y `ingestion.sintetico.load.load_corpus` lo carga exactamente
igual que cargó el JSON original.

## Los 8 componentes del §24

| Componente | Archivo | Qué decide |
|---|---|---|
| `CompanyGenerator` | `company_generator.py` | Importadores nuevos, mismo patrón `SIM260101A<letra>` que los 15 ya cargados, continuando la secuencia sin colisionar |
| `SupplierGenerator` | `supplier_generator.py` | Elige entre los 3 proveedores reales (`catalog.py`) — no inventa proveedores |
| `ProductGenerator` | `product_generator.py` | Una partida a partir de una ficha de catálogo YA existente — nunca una ficha nueva |
| `InvoiceGenerator` | `invoice_generator.py` | Fórmula de montos (verificada contra el corpus real), en `Decimal` |
| `COVEGenerator` | `cove_generator.py` | Número de COVE — deliberadamente delgado, mismo motivo que `ingestion/sintetico/load.py::_create_cove` |
| `PedimentoGenerator` | `pedimento_generator.py` | Ensambla el pedimento completo en la forma JSON que `parse_corpus` espera |
| `ErrorInjector` | `errors.py` | Las 3 anomalías nuevas implementadas |
| `GroundTruthGenerator` | `ground_truth_generator.py` | Empaqueta las anomalías en la lista que alimenta `intelligence.ground_truth_records` |

`catalog.py` no es un componente del §24: es el catálogo real (12 fichas,
3 proveedores) transcrito del corpus ya cargado, para que ningún
componente tenga que inventar un producto.

## Las 12 fichas son las MISMAS — condición de Persona 1

`synthetic/catalog.py::PRODUCT_CATALOG` se transcribió del JSON real
(`sintetico/corpus_espejo_v1_20260921.json` en MinIO), verificado campo
por campo el 13-oct. `test_no_declara_ningun_producto_fuera_del_catalogo_
de_12` (`tests/test_synthetic_corpus.py`) falla si algún componente
intentara declarar un `product_id` fuera de esos 12. Lo que SÍ es nuevo en
cada carga es el PEDIMENTO (número, fecha, importador, partidas) — la
misma mercancía, importada otra vez, por alguien distinto.

**Dos correcciones sobre las 12 fichas que valen la pena anotar:** al
transcribir los pares fracción/NICO reales del corpus para usarlos como
"valor correcto" de referencia, dos quedaban contaminados por una
anomalía ya sembrada en el corpus original (`P002` tenía `69111001`
—porcelana, de `P003`— en vez de su propio `73241001`; `P012` tenía
`76151002` —aluminio, de `P001`— en vez de su propio `73231001`,
la fracción real de esponjas/estropajos de acero, 7323.10). Corregido
contra el patrón temático de las demás filas del mismo producto antes de
escribir el catálogo — no se alimentó al generador con una fracción ya
contaminada.

## Las 3 de 6 anomalías implementadas, y por qué no las otras 3

Implementadas (`synthetic/errors.py`), ninguna exige una fuente jurídica
que todavía no está cargada:

- **`WRONG_IDENTIFIER`** — usa `regulatory.pedimento_identifier_
  requirements` (ADR 0010, cargada hoy mismo): un pedimento con clave de
  documento `V1` que no declara el identificador `V1` del Apéndice 8.
- **`INCONSISTENT_SKU_CLASSIFICATION`** — dos pedimentos, dos
  IMPORTADORES DISTINTOS (condición real: `uq_products_client_id_sku`),
  mismo `sku_override`, fracción distinta. Verificado contra Postgres
  real en `tests/test_synthetic_corpus_carga.py` — no sólo en el
  dataclass.
- **`MISSING_INCREMENTABLE`** — el importe de incrementables declarado
  omite un concepto real (flete) que la propia operación trae. Pura
  consistencia interna, sin fuente jurídica de por medio.

**Diferidas, las 3 por el mismo motivo exacto (§8.1 del maestro — nunca
inventar fundamento jurídico):**

- **`MISSING_NOM`**: verificado contra `regulatory.fraction_nom_
  requirements` (ADR 0003, 456 filas) — CERO filas para las 10 fracciones
  reales de las 12 fichas del catálogo. No hay ninguna fracción de este
  catálogo a la que pueda, hoy, faltarle una NOM real.
- **`MISSED_PROSEC`** / **`MISSED_PREFERENCE`**: `core/opportunity/
  engine.py` ya lo dice de frente — esas tasas son datos jurídicos con
  vigencia y fuente, y ni PROSEC/Regla 8a ni preferencias arancelarias
  están cargadas todavía (tarea 3, pendiente).

Si Persona 1 quiere estas tres, la única forma honesta es: o se abre una
13ª ficha de catálogo cuya fracción real SÍ tenga NOM/PROSEC/preferencia
cargada (lo cual el propio Persona 1 dijo que cambia las cifras y requiere
su revisión aparte), o se espera a que la tarea 3 cargue PROSEC/Regla 8a.
No se abre esa puerta en esta rama sin esa decisión.

## Tipo de cambio real — ya no hay 18.33 inventado

`synthetic/corpus.py::construir_corpus_nuevo` recibe `tasa_de_cambio`
como parámetro inyectado — nunca lo resuelve por su cuenta (mismo
criterio que `Money.convert()`, §22 maestro: quien necesita el dato lo
pide explícito). Probado con `database.repositories.exchange.
tasa_vigente` real contra mi Postgres local: los 5 pedimentos nuevos usan
5 tasas FIX reales y distintas (16.87–17.13), nunca un valor repetido.

**Hallazgo nuevo, no documentado antes, fuera del alcance de esta
tarea:** `regulatory.exchange_rates` tiene un hueco de vigencia real para
el rango 2026-09-01 a 2026-09-02 — la fila `valid_from=2026-08-31` quedó
con `valid_to=NULL` (como si fuera la más reciente) aunque ya existe una
fila `valid_from=2026-09-03` que debería haberla cerrado el día anterior.
`tasa_vigente()` devuelve `MultipleResultsFound` para cualquier fecha en
ese rango. El bug está en `ingestion/banxico/load.py` (la función que
cierra la versión anterior al cargar la siguiente), no en
`database/repositories/exchange.py`. No lo corregí aquí: Banxico no es
parte de las 6 tareas de hoy, y tocar su loader sin que Persona 1 lo pida
sería exactamente lo que CLAUDE.md pide no hacer ("trabaja sólo dentro del
alcance de la tarea"). Lo dejo anotado para que alguien lo abra aparte.

## Peso neto y rectificación (ADR 0011)

`net_weight_kg` (nuevo, `pedimento_items`) se puebla en las 5 partidas de
cable de acero generadas — con un factor de ingeniería genérico
(1.15 kg/m para cable 18 mm 6x36), marcado `SYNTHETIC` como todo lo demás,
nunca presentado como una medición real de ESTE producto. Con él, la
cuota compensatoria del cable (ADR 0009, fijada por kg) puede llevar
importe en vez de sólo señalarse sin monto.

`PED_SIM_020` rectifica a `PED_SIM_016` (`rectifies_pedimento_id`,
`rectification_number=1`) — mismo producto, misma clave `V1`, con el
identificador corregido. Demuestra el mecanismo del §10; no pretende ser
el único patrón de rectificación posible.

## Huecos de detección que esto NO resuelve (y de quién son)

Generar la anomalía no es lo mismo que poder medirla. Dos cables sueltos,
ya existentes, que esta carga no cierra:

- **`sku_history` nunca se pasa a `review_pedimento()`**
  (`apps/api/routers/pedimentos.py:216`, siempre `None`) — aunque el dato
  ya exista en `Product.sku`, nadie construye el histórico ni lo pasa al
  comparador. Mismo patrón que `required_identifiers` (ADR 0010): el dato
  ya está, el cableado en `core/shadow` es de quien lo decida (Persona 1 lo
  dijo explícito para los identificadores; aquí no se ha pedido, lo anoto
  para que no quede oculto).
- **`MISSING_INCREMENTABLE` no tiene detector** en
  `core/evaluation/deteccion.py::DETECTOR_POR_ERROR` — por eso
  `expected_detection=True` en vez de marcarlo indetectable: el hueco es de
  implementación, no de diseño, y así queda medible (recall 0% para este
  tipo) en vez de escondido.

## Qué falta para cargar esto de verdad (el plan que pide revisión)

1. **Confirmar que los 5 pedimentos nuevos (`PED_SIM_016`..`020`) se
   agregan al MISMO escenario** (`slug=corpus_espejo_v1`, mismo seed
   `20260921`) — no uno nuevo. Verificado: `load_corpus` ya resuelve el
   escenario existente por slug, no crea uno.
2. **Ningún producto nuevo** — verificado por test y por carga real contra
   Postgres (rollback). Los 181 veredictos de César sobre las 12 fichas
   existentes no se tocan: esta carga sólo agrega filas, nunca reescribe
   ni borra las 15 originales (`load_pedimento` es estrictamente
   aditivo-o-salta).
3. **Aplicar primero la migración `67e3c2617b54`** (peso neto +
   rectificación) donde se vaya a cargar — sin ella, `net_weight_kg`/
   `rectifies_pedimento_id` no existen como columnas.
4. **Decidir si corren `--target shared`** o se quedan locales mientras
   siga la demo de hoy — por ahora, sólo verificado contra mi Postgres
   local, dentro de una transacción revertida. Nada persistido en ningún
   lado.

Hasta que Persona 1 conteste estos 4 puntos, no corro `load_corpus` fuera
de un test con rollback.
