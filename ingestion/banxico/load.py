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


def _valid_to_para(session: Session, *, currency: str, new_valid_from: date) -> date | None:
    """`valid_to` de la fila que se va a insertar en `new_valid_from`.

    Bug real encontrado el 13-oct-2026: un backfill que carga una fecha
    MÁS VIEJA que la que ya es la más reciente (dos corridas, 6 y 7-oct,
    que no cubrieron el mismo rango) insertaba la fila vieja con
    `valid_to=NULL` -- "la más reciente" -- aunque ya existiera una fila
    posterior. `_close_previous_rate_versions` sólo mira hacia ATRÁS
    (cierra lo que ya estaba abierto); a la fila que se inserta ahora
    nadie le decía si YA nació cerrada porque algo más nuevo existe.

    `None` si `new_valid_from` sigue siendo la fecha más reciente de
    `currency` -- el caso normal, creciendo hacia adelante.
    """
    siguiente = (
        session.query(ExchangeRate)
        .filter(ExchangeRate.currency == currency, ExchangeRate.valid_from > new_valid_from)
        .order_by(ExchangeRate.valid_from.asc())
        .first()
    )
    if siguiente is None:
        return None
    return siguiente.valid_from - timedelta(days=1)


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
                valid_to=_valid_to_para(
                    session, currency=parsed.currency, new_valid_from=parsed.rate_date
                ),
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


def cerrar_vigencias_huerfanas(session: Session) -> int:
    """Repara filas YA cargadas con el bug del 13-oct-2026: `valid_to=NULL`
    aunque exista una fila posterior de la misma `currency` -- backfills
    anteriores a este fix pudieron dejarlas así (ver `_valid_to_para`).

    No es un `--reset`: no toca ninguna fila cuyo `valid_to` ya sea
    correcto, y no inventa ninguna fecha que no sea el `valid_from - 1
    día` de la fila que de verdad la sucede. Devuelve cuántas se
    corrigieron.
    """
    corregidas = 0
    for moneda in session.query(ExchangeRate.currency).distinct():
        (currency,) = moneda
        abiertas = (
            session.query(ExchangeRate)
            .filter(ExchangeRate.currency == currency, ExchangeRate.valid_to.is_(None))
            .all()
        )
        for fila in abiertas:
            correcto = _valid_to_para(session, currency=currency, new_valid_from=fila.valid_from)
            if correcto is not None:
                fila.valid_to = correcto
                corregidas += 1
    if corregidas:
        session.flush()
    return corregidas
