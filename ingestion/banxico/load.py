"""PARSED -> DATABASE del tipo de cambio FIX (USD/MXN).

Vigencia como cualquier otra tabla de `regulatory`, no una fila suelta por
día: un FIX publicado un viernes sigue vigente el fin de semana y
cualquier día inhábil hasta que el DOF publique el siguiente. Cerrar la
versión anterior al insertar una más nueva es el mismo patrón exacto que
`ingestion.snice.load._close_previous_fraction_versions` — no una
invención nueva para esta tabla.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING

from database.models.regulatory import ExchangeRate, LegalSource

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from ingestion.banxico.fix import ParsedExchangeRate

BANXICO_SLUG = "banxico"
DOF_INDICADORES_URL = "https://dof.gob.mx/indicadores_detalle.php"


def get_or_create_banxico_source(session: Session) -> LegalSource:
    """El `LegalSource` de Banco de México — quien determina el FIX.

    El canal que se lee es el portal del DOF (`indicadores_detalle.php`),
    no la API de Banxico: esa exige un token que este repo no tiene (regla
    9 CLAUDE.md). El valor es el mismo FIX en los dos casos — Banxico es
    quien lo determina (serie `SF43718`), el DOF sólo lo reproduce al
    siguiente día hábil por mandato del artículo 20 de la Ley del Banco de
    México.
    """
    existing = session.query(LegalSource).filter_by(slug=BANXICO_SLUG).one_or_none()
    if existing is not None:
        return existing

    source = LegalSource(
        slug=BANXICO_SLUG,
        name="Banco de México",
        authority="Banco de México",
        jurisdiction="MX",
        kind="OFFICIAL",
        base_url="https://www.banxico.org.mx",
        notes=(
            'Serie SF43718 ("Pesos por Dólar. FIX."), leída del portal del '
            "DOF (indicadores_detalle.php) y no de la API de Banxico: esa "
            "exige un token por correo a sie@banxico.org.mx que este repo "
            "no tiene. Mismo valor, canal distinto."
        ),
    )
    session.add(source)
    session.flush()
    return source


def _close_previous_rate_versions(session: Session, *, currency: str, new_valid_from: date) -> None:
    """Cierra cualquier versión de `currency` que siga abierta antes de
    `new_valid_from`. No toca una versión que ya empieza en o después de
    esa fecha -- eso lo revienta la propia `UniqueConstraint`, el
    comportamiento correcto ante una recarga accidental con la misma
    fecha."""
    anteriores = (
        session.query(ExchangeRate)
        .filter(
            ExchangeRate.currency == currency,
            ExchangeRate.valid_to.is_(None),
            ExchangeRate.valid_from < new_valid_from,
        )
        .all()
    )
    for anterior in anteriores:
        anterior.valid_to = new_valid_from - timedelta(days=1)
    if anteriores:
        session.flush()


def load_exchange_rates(
    session: Session,
    *,
    rates: list[ParsedExchangeRate],
    content_hash: str,
) -> int:
    """Inserta las filas que falten. Idempotente: una fecha ya cargada se
    salta (a diferencia de `tariff_headings`, aquí SÍ se espera recorrer el
    mismo rango más de una vez -- es una serie que crece todos los días
    hábiles, no un catálogo que se carga una sola vez). Devuelve cuántas
    se insertaron.
    """
    source = get_or_create_banxico_source(session)
    retrieved_at = datetime.now(UTC)

    insertadas = 0
    # En orden de fecha: así `_close_previous_rate_versions` siempre cierra
    # contra la fila que de verdad la precede, aunque `rates` llegue
    # desordenado.
    for parsed in sorted(rates, key=lambda r: r.rate_date):
        ya_existe = (
            session.query(ExchangeRate)
            .filter_by(currency=parsed.currency, valid_from=parsed.rate_date)
            .one_or_none()
        )
        if ya_existe is not None:
            continue
        _close_previous_rate_versions(
            session, currency=parsed.currency, new_valid_from=parsed.rate_date
        )
        session.add(
            ExchangeRate(
                currency=parsed.currency,
                rate=parsed.rate,
                data_origin="OFFICIAL",
                source_id=source.id,
                valid_from=parsed.rate_date,
                published_at=parsed.rate_date,
                source_url=DOF_INDICADORES_URL,
                source_document="Tipo de cambio FIX (Banxico SF43718), vía DOF",
                content_hash=content_hash,
                retrieved_at=retrieved_at,
            )
        )
        insertadas += 1

    session.flush()
    return insertadas
