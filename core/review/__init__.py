"""Revisión completa de un pedimento: los cuatro motores encadenados.

    Espejo → Money Finder → Audit → Opportunity

Existe porque los cuatro módulos estaban construidos y probados pero ninguno
llegaba al producto: `core/taxation`, `core/shadow`, `core/audit` y
`core/opportunity` no eran invocados por ningún endpoint, y la única fila de
`risk_findings` la había escrito el seed. Se podía enseñar que el sistema
clasifica; no que encuentra dinero (Persona 1, 2026-09-08).

USO

    from core.review import LineInput, review_pedimento

    revision = review_pedimento([
        LineInput(
            declared=DeclaredItem(line_number=1, fraction_code="85285900", ...),
            expected=ExpectedItem(line_number=1, fraction_code="84713001", ...),
            transaction_value=Money(amount=Decimal("100000"), currency="MXN"),
            declared_rates=TaxRates(igi_rate=Decimal("0.15"), ...),
            expected_rates=TaxRates(igi_rate=Decimal("0.00"), ...),
        ),
    ])

    revision.total_exposure   # lo omitido en todo el pedimento
    revision.is_complete      # False si algo no se pudo comprobar
    revision.summary()

QUÉ NO HACE

No toca la base, no llama a ningún proveedor de IA y no consulta el catálogo
arancelario (§29). Recibe las partidas ya armadas, con sus tasas. Quien las
arma es `apps/api/routers/pedimentos.py`, que sí tiene la sesión.

Las tasas de IVA y DTA vienen de quien llama, no de aquí: son las de la
operación. Codificarlas sería inventar fundamento jurídico y, peor, congelarlo
—el día que cambien en el DOF el sistema seguiría calculando con las viejas—.
El IGI sí sale del catálogo, porque es propio de cada fracción.
"""

from __future__ import annotations

from core.review.engine import REVIEW_VERSION, review_pedimento
from core.review.types import LineInput, PedimentoReview

__all__ = [
    "REVIEW_VERSION",
    "LineInput",
    "PedimentoReview",
    "review_pedimento",
]
