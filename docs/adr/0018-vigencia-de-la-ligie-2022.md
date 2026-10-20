# ADR 0018 — La vigencia de la LIGIE 2022 y la tarifa como foto

- **Fecha:** 2026-10-20
- **Estado:** aceptado (2026-10-20, por delegación de Persona 1). La parte 1 se
  implementa; la parte 2 queda propuesta.
- **Decide:** Persona 1, que delega lo técnico; queda escrito aquí.

## Contexto

### 1. Fecha de publicación tomada como inicio de vigencia

Todo lo cargado de la LIGIE 2022 empezaba su vigencia el **2022-06-07**, que es
la fecha en que se publicó en el DOF. La ley entró en vigor el **2022-12-12**:
el Transitorio Primero la condiciona a que el SAT declare listos sus sistemas,
y la Cuarta Resolución de Modificaciones a las RGCE 2022 (DOF 5-dic-2022, punto
SEGUNDO) lo declaró («entrará en vigor el 12 de diciembre de 2022»). Esto se
verificó en el documento primario.

Afectaba a 29 210 filas de 7 tablas: `tariff_fractions` 8 135, `nicos`
11 502, `tariff_headings` 6 855, `tariff_heading_groups` 1 024,
`legal_documents` 1, `legal_rules` 94 y `legal_chunks` 1 599.

### 2. La tarifa es una foto de abril de 2026

El catálogo se cargó del Excel de SNICE `FRACCIONESARANCELARIAS-LIGIE_20260420`,
es decir, la tarifa **tal como estaba el 20-abr-2026**, con todas las
modificaciones acumuladas. Al fecharla desde 2022 se afirma que las tasas de
2026 regían en 2023, 2024 y 2025. Entre 2022 y 2026 el índice de SNICE lista
siete decretos que modifican la Tarifa (22-abr-2024, 8-may-2024, 19-dic-2024,
10-nov-2025, 26-mar-2026, 23-abr-2026 y 13-oct-2026), además de la reforma del
29-dic-2025 que cita el Texto Vigente de Diputados. Dos de ellos son
**posteriores** a la foto.

**Impacto medido hoy en el corpus: ninguno.** Las 188 partidas son de marzo a
septiembre de 2026. El decreto del 23-abr-2026 es el único que cita fracciones
del corpus (7323.10.01, 7323.93.05, 7323.99.99 y 7324.10.01), y las tasas que
fija (35 % y 25 %) son las que ya están cargadas. Sólo hay 4 decisiones con
fecha de 2024, y son de clasificación: no usan tasas.

## Decisión

**Parte 1 (implementada).** `LIGIE_VALID_FROM = 2022-12-12` en los cargadores
(`ingestion/snice/load.py` e `ingestion/diputados/load.py`), y la publicación
pasa a `LIGIE_PUBLISHED_AT`. Lo ya cargado se corrige con
`python -m ingestion.snice.corregir_vigencia --target local`, que:

- sólo toca filas no sintéticas con inicio 2022-06-07;
- deja la publicación en `published_at`;
- no borra ni crea filas, así que los `id` no cambian y las decisiones siguen
  apuntando a la misma fracción;
- es idempotente.

Entre el 2022-06-07 y el 2022-12-11 no queda tarifa: una operación de ese
periodo se responde como «fracción no vigente». Es lo correcto, porque no
tenemos la LIGIE 2020 y evaluarla con la de 2022 sería inventar.

**Parte 2 (propuesta, no implementada).** Versionar las tasas por decreto. La
base sería el texto original de la LIGIE 2022 (Cámara de Diputados), y sobre
ella se aplicarían los decretos en orden, cada uno desde su entrada en vigor.
Los decretos vienen en el DOF como tablas HTML (fracción, descripción, unidad,
IGI, IGE), que el extractor de `ingestion/se/tablas_html.py` ya lee. Al final,
el resultado debe coincidir con la foto de SNICE del 20-abr-2026: esa es la
prueba. Mientras no exista, una operación anterior a 2026 se evalúa con tasas
de 2026, y eso se dice en el ADR en vez de callarlo.
