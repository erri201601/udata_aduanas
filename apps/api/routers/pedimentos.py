"""Revisión de un pedimento completo: Espejo → Money Finder → Audit → Opportunity.

POR QUÉ ESTE ENDPOINT EXISTE

Los cuatro motores estaban construidos y probados pero ninguno llegaba al
producto. La única fila de `risk_findings` la había escrito el seed, y
`opportunity_findings` estaba vacía. Se podía enseñar que el sistema clasifica;
no que encuentra dinero (Persona 1, 2026-09-08).

LO QUE SE PUEDE COMPROBAR SIN CLASIFICAR

Tres cosas salen del propio documento y no necesitan que el motor llegue a una
fracción. Se agrupan en `_espejo_documental` porque comparten eso:

  · el país, contra el proveedor de la factura;
  · el NICO, contra el catálogo: si el declarado NO EXISTE en su fracción, eso
    el catálogo lo sabe solo. Si existe, saber si es el que corresponde a la
    mercancía exige ficha técnica, y se declara como hueco;
  · el valor en aduana, contra la aritmética de la propia partida: precio
    pagado más incrementables. Una partida que se contradice a sí misma se
    delata sin mirar el encabezado ni el DTA (Persona 1, 21-sep).
  · el IGI, contra la tarifa de la fracción DECLARADA. Aunque esa fracción
    estuviera equivocada, el importe tiene que cuadrar con la tasa de la que
    se declaró.
  · el IVA, contra su base: valor en aduana + IGI + DTA, con las tasas que
    pasa quien audita.
  · la unidad, contra el Apéndice 7 del Anexo 22.

Ninguna de las cuatro necesita que el motor clasifique, y por eso se miden
aunque la clasificación no se sostenga (Persona 1, 22-sep).

EL PAÍS DE ORIGEN SE CONTRASTA CONTRA EL PROVEEDOR

No hace falta fuente externa: el documento ya dice de dónde es el proveedor, y
una partida cuyo país difiere del suyo merece una mirada. NO es un error —un
pedimento con orígenes mixtos es legítimo— y por eso viaja con
`origin_source = SUPPLIER`, que hace que el Espejo lo emita como revisión
humana con el motivo escrito, no como acusación (Persona 1, 21-sep).

Si la partida no está ligada a una factura no hay proveedor que consultar, y
entonces no se compara: la partida declara que el origen no se pudo contrastar
en vez de darse por limpia.

DE DÓNDE SALEN LAS TASAS

El IGI sale del catálogo, por fracción y por fecha de operación: es lo propio
de cada mercancía y es lo que hace la diferencia cuando la fracción declarada
no es la correcta.

El IVA, el DTA y el IEPS los pasa quien llama. No están codificados aquí a
propósito: serían fundamento jurídico inventado, y quedarían congelados el día
que cambien en el DOF. Cuando Persona 2 cargue la Ley del IVA y la Ley Federal
de Derechos como fuentes, esto las consultará y registrará su `source_id`.

Si falta cualquiera de las dos tasas de IGI —porque la fracción declarada no
existe en la tarifa cargada— la partida NO se cuantifica. El hallazgo se emite
igual, sin monto: es un riesgo de cumplimiento real aunque no se sepa cuánto
cuesta. Inventar un cero daría una cifra plausible y falsa.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any, Final

import sqlalchemy as sa
from core.review import LineInput, PedimentoReview, review_pedimento
from core.shadow import DeclaredItem, ExpectedItem
from core.shadow.types import ORIGEN_DEL_PROVEEDOR
from core.taxation import Money, TaxRates
from database.models import (
    FractionNomRequirement,
    Invoice,
    InvoiceItem,
    Pedimento,
    PedimentoItem,
    Supplier,
)
from database.repositories import save_review
from database.repositories.exchange import tasa_vigente
from database.repositories.tariff import TariffCatalogRepository
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from apps.api.clasificacion import clasificar_borrador
from apps.api.db import SessionDep
from apps.api.dna import cargar_borrador

router = APIRouter(prefix="/pedimentos", tags=["pedimentos"])

#: El pedimento redondea a centavos y el cálculo de aquí también.
_CENTAVOS: Final = Decimal("0.01")

#: Lo que se puede comprobar sin haber clasificado. Si nada de esto consta, la
#: partida no tiene espejo y se reporta como no verificable.
_COMPROBABLE_SIN_CLASIFICAR: Final = ("country_of_origin", "valid_nico_codes", "customs_value")


class ReviewRequest(BaseModel):
    """Las tasas de la operación. Todas opcionales; sin ellas no hay monto."""

    iva_rate: Decimal | None = Field(
        default=None,
        description="Fracción, no porcentaje: 0.16, no 16. En región fronteriza 0.08.",
    )
    dta_rate: Decimal | None = Field(
        default=None, description="Derecho de Trámite Aduanero ad valorem. El 8 al millar es 0.008."
    )
    dta_fixed: Decimal | None = Field(
        default=None, description="Cuota fija de DTA, cuando el régimen la usa en vez de la tasa."
    )
    ieps_rate: Decimal | None = Field(default=None, description="Sólo en mercancías que lo causan.")


class ReviewResponse(BaseModel):
    """Lo que se encontró, y sobre todo lo que no se pudo comprobar."""

    review_id: uuid.UUID
    pedimento_id: uuid.UUID
    findings: int
    worst_severity: str | None = None

    is_complete: bool
    """`False` significa que algo quedó sin revisar. Un pedimento incompleto
    NO está limpio: está sin verificar."""

    unverifiable: list[str] = Field(default_factory=list)

    total_exposure: Decimal | None = None
    total_recoverable: Decimal | None = None
    currency: str | None = None
    mixed_currencies: bool = False

    opportunities: int = 0
    quantified_opportunities: int = 0

    is_simulation: bool = True
    """§33: mientras alguna entrada sea SYNTHETIC, esto es una simulación."""

    lines_without_expectation: int = 0
    """Partidas para las que no se pudo construir un espejo — sin producto
    ligado, o sin Product DNA. Son las que hacen `is_complete` falso."""

    summary: str


@router.post(
    "/{pedimento_id}/review",
    status_code=status.HTTP_201_CREATED,
    summary="Revisa el pedimento contra su espejo y persiste los hallazgos",
)
def revisar(
    pedimento_id: uuid.UUID, peticion: ReviewRequest, session: SessionDep
) -> ReviewResponse:
    """Corre los cuatro motores sobre el pedimento y guarda el resultado.

    Nunca devuelve 500 por no poder revisar una partida. Una partida sin
    espejo es un resultado legítimo —va a `unverifiable`— y la revisión se
    persiste igual: saber qué NO se revisó es justamente lo que este endpoint
    aporta sobre no tener nada.
    """
    pedimento = session.get(Pedimento, pedimento_id)
    if pedimento is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "pedimento no encontrado")

    partidas = session.scalars(
        sa.select(PedimentoItem)
        .where(PedimentoItem.pedimento_id == pedimento_id)
        .order_by(PedimentoItem.line_number)
    ).all()
    if not partidas:
        raise HTTPException(status.HTTP_409_CONFLICT, "el pedimento no tiene partidas")

    catalogo = TariffCatalogRepository(session)
    fecha = pedimento.operation_date

    lineas: list[LineInput] = []
    sin_espejo = 0

    for partida in partidas:
        esperada = _construir_espejo(session, partida, fecha, catalogo, peticion)
        if esperada is None:
            sin_espejo += 1

        valor = _valor(partida)
        declaradas, esperadas = _tasas(
            catalogo,
            fecha,
            peticion,
            declarada=partida.declared_fraction_code,
            esperada=esperada.fraction_code if esperada else None,
        )

        lineas.append(
            LineInput(
                declared=_declarada(partida),
                expected=esperada,
                transaction_value=valor,
                declared_rates=declaradas,
                expected_rates=esperadas,
                # Lo derivado de un pedimento sintético es sintético (§10).
                is_simulation=pedimento.is_simulation or partida.data_origin == "SYNTHETIC",
            )
        )

    revision = review_pedimento(lineas)

    corrida = save_review(
        session,
        revision,
        pedimento_id=pedimento_id,
        item_ids={p.line_number: p.id for p in partidas},
        data_origin=pedimento.data_origin,
    )
    session.commit()

    return _respuesta(corrida.id, pedimento_id, revision, sin_espejo)


# ── Armado de cada partida ───────────────────────────────────────────────────


def _declarada(partida: PedimentoItem) -> DeclaredItem:
    """La partida tal como viene en el pedimento, sin interpretarla."""
    return DeclaredItem(
        line_number=partida.line_number,
        description=partida.description,
        fraction_code=partida.declared_fraction_code,
        nico_code=partida.declared_nico_code,
        country_of_origin=partida.country_of_origin,
        customs_value=partida.customs_value,
        customs_value_currency=partida.customs_value_currency,
        applied_nom_codes=tuple(partida.applied_nom_codes or ()),
        identifiers=dict(partida.identifiers or {}),
        unit=partida.commercial_unit,
        igi_amount=partida.igi_amount,
        vat_amount=partida.vat_amount,
    )


def _pais_del_proveedor(session: SessionDep, partida: PedimentoItem) -> str | None:
    """País del proveedor de la factura de esta partida. `None` si no consta.

    `Pedimento` no guarda proveedor: se llega por la factura
    (`partida → invoice_item → invoice → supplier`). Sin ese enlace no hay
    contra qué contrastar, y se devuelve `None` en vez de suponer.
    """
    if partida.invoice_item_id is None:
        return None
    return session.scalar(
        sa.select(Supplier.country)
        .select_from(InvoiceItem)
        .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
        .join(Supplier, Supplier.id == Invoice.supplier_id)
        .where(InvoiceItem.id == partida.invoice_item_id)
    )


def _valor_esperado(
    session: SessionDep, partida: PedimentoItem, fecha: date
) -> tuple[Decimal | None, str | None]:
    """Valor en aduana según la propia partida: precio pagado + incrementables,
    convertido a MXN con el FIX vigente en `fecha` si la factura viene en
    otra divisa.

    `None` si falta cualquiera de los dos, si vienen en divisas distintas
    (sumar importes de monedas distintas daría una cifra falsa), o si la
    divisa no es MXN y no hay tipo de cambio cargado para `fecha` — un
    faltante NO se sustituye por cero ni por un valor sin convertir: las
    dos son una afirmación, y aquí no consta.

    Antes de `ingestion.banxico` (2026-10-06) esto SIEMPRE devolvía la
    divisa de la factura tal cual, y `core/shadow/compare.py` comparaba
    USD contra MXN y reportaba "divisa distinta" en cada partida real del
    corpus (invoices 100% USD, pedimentos 100% MXN, verificado contra la
    base compartida) — nunca llegaba a comparar el monto.
    """
    if partida.price_paid is None or partida.incrementables is None:
        return None, None
    monedas = {partida.price_paid_currency, partida.incrementables_currency} - {None}
    if len(monedas) > 1:
        return None, None
    moneda = partida.price_paid_currency or partida.customs_value_currency
    valor = partida.price_paid + partida.incrementables
    if moneda is None or moneda == "MXN":
        return valor, moneda
    tasa = tasa_vigente(session, on_date=fecha, currency=moneda)
    if tasa is None:
        return None, None
    convertido = Money(amount=valor, currency=moneda).convert(to="MXN", rate=tasa)
    return convertido.amount, convertido.currency


def _dta(valor: Decimal, peticion: ReviewRequest) -> Decimal | None:
    """El DTA de la partida con las tasas de la operación. `None` si no se pasaron.

    La tasa la pasa quien audita: codificarla aquí sería fundamento jurídico
    inventado y quedaría congelada el día que cambie en el DOF.
    """
    if peticion.dta_rate is not None:
        return valor * peticion.dta_rate
    return peticion.dta_fixed


def _fiscal_esperado(
    partida: PedimentoItem, fecha: date, catalogo: TariffCatalogRepository, peticion: ReviewRequest
) -> tuple[Decimal | None, Decimal | None]:
    """IGI e IVA que deberían haberse declarado. `None` cuando no se puede saber.

    El IGI sale de la tarifa de la fracción DECLARADA: no hace falta clasificar
    para exigir que el importe cuadre con la tasa de la que se declaró. El IVA
    sale de su base —valor en aduana + IGI + DTA— con las tasas de la
    operación. Si falta cualquiera de las piezas se devuelve `None` y la
    partida lo declara, en vez de compararse contra un número supuesto.
    """
    if partida.customs_value is None or not partida.declared_fraction_code:
        return None, None

    tasa = catalogo.igi_rate(on_date=fecha, fraction_code=partida.declared_fraction_code)
    if tasa is None:
        return None, None
    igi = (partida.customs_value * tasa).quantize(_CENTAVOS)

    dta = _dta(partida.customs_value, peticion)
    if dta is None or peticion.iva_rate is None:
        return igi, None
    base = partida.customs_value + igi + dta.quantize(_CENTAVOS)
    return igi, (base * peticion.iva_rate).quantize(_CENTAVOS)


def _espejo_documental(
    session: SessionDep,
    partida: PedimentoItem,
    fecha: date,
    catalogo: TariffCatalogRepository,
    peticion: ReviewRequest,
) -> dict[str, Any]:
    """Lo que se puede esperar SIN clasificar. Sale del documento, no del motor."""
    pais = _pais_del_proveedor(session, partida)
    valor, moneda = _valor_esperado(session, partida, fecha)
    igi, iva = _fiscal_esperado(partida, fecha, catalogo, peticion)
    # `None` y `False` dicen cosas distintas: sin catálogo cargado no se puede
    # afirmar que una unidad no exista, y acusar ahí sería culpar al pedimento
    # de un hueco nuestro.
    unidad_conocida = (
        catalogo.unidad_existe(on_date=fecha, code=partida.commercial_unit)
        if partida.commercial_unit and catalogo.hay_unidades(on_date=fecha)
        else None
    )
    return {
        "igi_amount": igi,
        "vat_amount": iva,
        "declared_unit_is_known": unidad_conocida,
        "country_of_origin": pais,
        "origin_source": ORIGEN_DEL_PROVEEDOR if pais else None,
        "valid_nico_codes": (
            catalogo.nicos(on_date=fecha, fraction_code=partida.declared_fraction_code)
            if partida.declared_fraction_code
            else None
        ),
        "customs_value": valor,
        "customs_value_currency": moneda,
    }


def _nom_exigidas(
    session: SessionDep, fecha: date, fraccion: str | None
) -> tuple[tuple[str, ...] | None, tuple[str, ...]]:
    """Qué NOM exige esta fracción, y cuáles quedan por comprobar a mano.

    Devuelve `(exigidas, acotadas)`:

    - `exigidas` son las que aplican a TODA la fracción. `()` significa «no
      exige ninguna» y permite declarar la partida limpia en ese campo;
      `None` significa «no lo sé» y la manda a `unverifiable`.
    - `acotadas` son las que el anexo limita con un «Únicamente: …». No entran
      en `exigidas` y se reportan aparte.

    POR QUÉ LAS ACOTADAS NO ACUSAN

    De las 456 correlaciones cargadas, 306 traen acotación: la NOM aplica sólo
    a una parte de la fracción —sólo leche descremada dentro de una fracción de
    leche en polvo, o sólo el punto 9.2 de la norma—. Decidir si la mercancía
    cae dentro exige leerla, y `MISSING_NOM` es una acusación contra el agente
    aduanal. Se le enseña el texto a una persona en vez de adivinar por ella.

    `None` SÓLO SI NO HAY CATÁLOGO

    Si el Anexo 2.4.1 está cargado y esta fracción no aparece en él, eso no es
    desconocimiento: es que no exige NOM. Devolver `None` ahí dejaría la
    partida como no verificable para siempre. Misma disciplina que
    `hay_unidades` con el Anexo 22.
    """
    if not fraccion:
        return None, ()

    vigentes = sa.and_(
        FractionNomRequirement.valid_from <= fecha,
        sa.or_(
            FractionNomRequirement.valid_to.is_(None),
            FractionNomRequirement.valid_to >= fecha,
        ),
    )
    hay_catalogo = session.scalar(sa.select(FractionNomRequirement.id).where(vigentes).limit(1))
    if hay_catalogo is None:
        return None, ()

    filas = session.execute(
        sa.select(FractionNomRequirement.nom_code, FractionNomRequirement.scope_note).where(
            vigentes, FractionNomRequirement.fraction_code == fraccion
        )
    ).all()

    exigidas = tuple(dict.fromkeys(f.nom_code for f in filas if not f.scope_note))
    acotadas = tuple(f"{f.nom_code} — Únicamente: {f.scope_note}" for f in filas if f.scope_note)
    return exigidas, acotadas


def _nico_esperado(
    catalogo: TariffCatalogRepository, fecha: date, fraccion: str | None
) -> str | None:
    """El NICO que corresponde a la fracción esperada, SÓLO si no hay duda.

    6 555 de las 8 135 fracciones vigentes tienen un único NICO. En esas no hay
    nada que elegir: el catálogo lo dice y el Espejo puede esperarlo con la
    misma certeza con la que espera la fracción.

    Con varios se devuelve `None`. Elegir entre ellos exige la ficha técnica
    —un NICO distingue por materia, uso o presentación— y suponerlo acusaría al
    pedimento de un NICO equivocado con una expectativa inventada, que es peor
    que declarar el hueco.

    Misma disciplina que el descarte de la RGI 6: resolver sólo cuando queda
    uno, y no por mayoría ni por orden.
    """
    if not fraccion:
        return None
    vigentes = catalogo.nicos(on_date=fecha, fraction_code=fraccion)
    if vigentes is None or len(vigentes) != 1:
        return None
    return vigentes[0]


def _construir_espejo(
    session: SessionDep,
    partida: PedimentoItem,
    fecha: date,
    catalogo: TariffCatalogRepository,
    peticion: ReviewRequest,
) -> ExpectedItem | None:
    """Clasifica el producto de la partida SIN mirar lo declarado (§36).

    Devuelve `None` cuando no hay con qué: sin producto ligado o sin Product
    DNA no hay expectativa, y la partida se reporta como no verificable. Un
    `ExpectedItem` vacío la haría pasar por limpia.
    """
    documental = _espejo_documental(session, partida, fecha, catalogo, peticion)

    if (
        partida.product_id is None
        or (borrador := cargar_borrador(session, partida.product_id)) is None
    ):
        # Sin producto ligado no se puede clasificar, pero el país, el NICO y la
        # aritmética del valor SÍ se pueden contrastar. Se devuelve lo que se
        # puede comprobar en vez de dejar la partida sin mirar.
        if not any(documental[campo] is not None for campo in _COMPROBABLE_SIN_CLASIFICAR):
            return None
        return ExpectedItem(
            line_number=partida.line_number,
            is_resolved=False,
            required_nom_codes=None,
            required_identifiers=None,
            **documental,
        )

    # POR EL MISMO CAMINO QUE EL ENDPOINT, NO POR UNA COPIA
    #
    # Esto llamaba a `classify_product` directamente, sin pasarle `legal_refs`.
    # El motor devolvía entonces `RESOLVED` con `code = None` —resuelto a nada—
    # y `is_resolved` quedaba en falso, así que el Espejo NUNCA llegaba a
    # comparar fracciones. La métrica del §26 marcaba `WRONG_FRACTION` 0 de 6
    # y parecía un límite del clasificador: era este atajo.
    #
    # Aislado el 23-sep sobre la misma vajilla, mismos términos y mismo
    # catálogo:
    #
    #     sin legal_refs : RESOLVED  code=None
    #     con legal_refs : RESOLVED  code=69111001
    #
    # `clasificar_borrador` es la función que usa `POST /products/{id}/classify`
    # y que el harness de `hs_accuracy` mide a propósito. Que el Espejo use otra
    # es exactamente lo que su docstring advierte que no se haga.
    outcome = clasificar_borrador(
        session,
        borrador,
        operation_date=fecha,
        trade_flow="IMPORT",
    ).outcome

    return ExpectedItem(
        line_number=partida.line_number,
        fraction_code=outcome.code,
        # El NICO de la fracción ESPERADA, no de la declarada. Sin esto el
        # Espejo no tenía expectativa de NICO en ninguna partida y las 180 del
        # corpus arrastraban el mismo hueco: «saber si es el que corresponde
        # exige la ficha técnica». Para las fracciones de un solo NICO eso no
        # era cierto — no hacía falta ninguna ficha, sólo mirar el catálogo.
        nico_code=_nico_esperado(catalogo, fecha, outcome.code),
        # `is_resolved` sale del contrato de evidencia, no de que el motor haya
        # llegado a un código: una clasificación que no se sostiene no puede
        # usarse para acusar a nadie.
        is_resolved=outcome.code is not None,
        confidence=outcome.trace.confidence,
        # Lo que el extractor declaró que le faltó. Aquí sí es `()` cuando la
        # ficha está completa: se consultó y no falta nada.
        missing_technical_fields=borrador.missing_information,
        # Desde el 4-oct el Anexo 2.4.1 está cargado: ya se puede decir qué NOM
        # exige una fracción. Las acotadas van aparte, a la vista de una
        # persona — ver `_nom_exigidas`.
        required_nom_codes=_nom_exigidas(session, fecha, outcome.code)[0],
        # Los identificadores siguen en `None`: el Apéndice 8 cargado es el
        # CATÁLOGO de códigos, y saber cuáles existen no dice cuáles exige una
        # operación. Decir «no exige ninguno» sería afirmar sin fuente.
        required_identifiers=None,
        **documental,
    )


def _valor(partida: PedimentoItem) -> Money | None:
    if partida.customs_value is None or partida.customs_value_currency is None:
        return None
    return Money(amount=partida.customs_value, currency=partida.customs_value_currency)


def _tasas(
    catalogo: TariffCatalogRepository,
    fecha: date,
    peticion: ReviewRequest,
    *,
    declarada: str | None,
    esperada: str | None,
) -> tuple[TaxRates | None, TaxRates | None]:
    """Tasas de la fracción declarada y de la esperada.

    Si falta cualquiera de las dos se devuelven las dos en `None`: cuantificar
    con una sola daría una diferencia contra cero, que es un número inventado.
    """
    if declarada is None or esperada is None:
        return None, None

    igi_declarada = catalogo.igi_rate(on_date=fecha, fraction_code=declarada)
    igi_esperada = catalogo.igi_rate(on_date=fecha, fraction_code=esperada)
    if igi_declarada is None or igi_esperada is None:
        return None, None

    comunes = {
        "iva_rate": peticion.iva_rate or Decimal("0"),
        "dta_rate": peticion.dta_rate or Decimal("0"),
        "dta_fixed": peticion.dta_fixed,
        "ieps_rate": peticion.ieps_rate or Decimal("0"),
    }
    return (
        TaxRates(igi_rate=igi_declarada, **comunes),
        TaxRates(igi_rate=igi_esperada, **comunes),
    )


def _respuesta(
    review_id: uuid.UUID,
    pedimento_id: uuid.UUID,
    revision: PedimentoReview,
    sin_espejo: int,
) -> ReviewResponse:
    oportunidades = revision.opportunities
    return ReviewResponse(
        review_id=review_id,
        pedimento_id=pedimento_id,
        findings=len(revision.findings),
        worst_severity=revision.worst_severity,
        is_complete=revision.is_complete,
        unverifiable=list(revision.unverifiable),
        total_exposure=revision.total_exposure,
        total_recoverable=revision.total_recoverable,
        currency=revision.currency,
        mixed_currencies=revision.mixed_currencies,
        opportunities=len(oportunidades.opportunities) if oportunidades else 0,
        quantified_opportunities=sum(1 for o in oportunidades.opportunities if o.is_quantified)
        if oportunidades
        else 0,
        is_simulation=revision.is_simulation,
        lines_without_expectation=sin_espejo,
        summary=revision.summary(),
    )
