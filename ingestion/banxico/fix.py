"""RAW -> PARSED del tipo de cambio FIX (USD/MXN) publicado en el DOF.

QUÉ ES

El FIX es la serie que Banco de México calcula y publica, y que el DOF
reproduce al día siguiente hábil por mandato del artículo 20 de la Ley del
Banco de México — es el tipo de cambio "para solventar obligaciones
denominadas en moneda extranjera pagaderas en la República Mexicana", el
mismo que exige convertir el valor de una factura en dólares a pesos para
un pedimento. En el catálogo de series de Banxico es `SF43718`
("Pesos por Dólar. FIX.").

POR QUÉ NO ES LA API DE BANXICO

`https://www.banxico.org.mx/SieAPIRest/service/v1/series/SF43718/data`
existe y es la fuente primaria, pero exige un token que se pide por correo
a `sie@banxico.org.mx` — no es un secreto que este repo pueda tener hoy
(regla 9 CLAUDE.md, y el repo es público desde el 28-sep).

El DOF publica la MISMA serie, sin token, en una página de consulta
pública: `https://dof.gob.mx/indicadores_detalle.php`. Verificado el
2026-10-06 contra un rango real (01 al 06 de octubre): HTML tabular
simple, `Fecha` (`DD-MM-AAAA`) + `Valor` (6 decimales), sin JavaScript de
por medio — el mismo patrón de scraping público que ya usan
`ingestion.dof`/`ingestion.snice` para otras fuentes del propio DOF.

```
GET indicadores_detalle.php?cod_tipo_indicador=158&dfecha=DD/MM/AAAA&hfecha=DD/MM/AAAA
```

`cod_tipo_indicador=158` es "DOLAR" en el `<select>` del formulario real de
esa página — verificado contra su HTML, no supuesto. Los demás valores del
mismo `<select>` (UDIS=159, CCP=160, TIIE=165/166...) quedan fuera: hoy
sólo hace falta USD/MXN (el corpus espejo sólo tiene facturas en USD y
pedimentos en MXN, verificado contra la base compartida).

VIGENCIA: EL FIX NO TRAE UN VALOR POR CADA DÍA DEL CALENDARIO

Sábados, domingos y días inhábiles no tienen fila propia — el valor del
último día hábil SIGUE VIGENTE hasta que se publique el siguiente. Esta
función sólo devuelve las filas que el documento trae; cerrar la vigencia
del valor anterior al cargar uno nuevo es trabajo de
`ingestion.banxico.load` (mismo patrón que
`ingestion.snice.load._close_previous_fraction_versions`), no de aquí.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

FIX_URL = "https://dof.gob.mx/indicadores_detalle.php"

#: "DOLAR" en el <select name="cod_tipo_indicador"> del formulario real de
#: la página -- verificado contra su HTML (2026-10-06).
COD_TIPO_INDICADOR_DOLAR = 158

CURRENCY = "USD"

_ROW_RE = re.compile(
    r'<td[^>]*class="txt"[^>]*>\s*(\d{2}-\d{2}-\d{4})\s*</td>\s*'
    r'<td[^>]*class="txt"[^>]*>\s*([\d.]+)\s*</td>'
)


@dataclass(frozen=True)
class ParsedExchangeRate:
    currency: str
    rate_date: date
    rate: Decimal


def fix_url(*, start: date, end: date) -> str:
    """La URL exacta que arma el formulario real -- `dfecha`/`hfecha` en
    `DD/MM/AAAA`, nunca ISO: así es como esa página los espera."""
    return (
        f"{FIX_URL}?cod_tipo_indicador={COD_TIPO_INDICADOR_DOLAR}"
        f"&dfecha={start.strftime('%d/%m/%Y')}&hfecha={end.strftime('%d/%m/%Y')}"
    )


def parse_fix_html(html: str) -> list[ParsedExchangeRate]:
    """Filas (fecha, valor) reales de la tabla. Vacía si el rango no trae
    ninguna -- no es un error, puede ser un rango sin días hábiles o
    posterior al último publicado."""
    filas = []
    for fecha_str, valor_str in _ROW_RE.findall(html):
        fecha = datetime.strptime(fecha_str, "%d-%m-%Y").date()
        filas.append(
            ParsedExchangeRate(currency=CURRENCY, rate_date=fecha, rate=Decimal(valor_str))
        )
    return filas
