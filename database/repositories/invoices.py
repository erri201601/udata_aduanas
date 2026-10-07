"""La divisa de la factura comercial ligada a una partida.

Separado para que `apps.api.routers.pedimentos` (el Espejo) y
`apps.evaluacion.deteccion_26` (la métrica) lean la MISMA consulta — el
bug real que corrigió esto (Erick, 7-oct) fue justo que el Espejo leía
`partida.price_paid_currency` creyendo que era la divisa de la factura, y
no lo es: esa divisa es la en que la PARTIDA imprime su propio precio
pagado (siempre MXN, Ley Aduanera), no en la que se emitió la factura
original. Ver docstring de `apps.api.routers.pedimentos._tipo_de_cambio_esperado`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa

from database.models import Invoice, InvoiceItem, PedimentoItem

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def divisa_de_la_factura(session: Session, partida: PedimentoItem) -> str | None:
    """`Invoice.currency` de la factura ligada a esta partida.

    `None` si la partida no tiene factura ligada (`invoice_item_id` es
    `None`) — sin ese enlace no hay con qué saber la divisa, y se
    devuelve `None` en vez de suponer MXN.
    """
    if partida.invoice_item_id is None:
        return None
    return session.scalar(
        sa.select(Invoice.currency)
        .select_from(InvoiceItem)
        .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
        .where(InvoiceItem.id == partida.invoice_item_id)
    )
