"""Las seis Reglas Generales de Interpretación, como evaluadores separados.

§18 del maestro: "No implementar clasificación como un prompt gigante.
Construir una máquina de evaluación." Cada regla es una clase con la misma
interfaz, evalúa una precondición concreta y devuelve un estado explícito.

REGLAS NO IMPLEMENTADAS EN v0.1

RGI 2, 4 y 5 no están implementadas, pero NO se saltan en silencio: detectan si
sus precondiciones se cumplen y, en ese caso, devuelven
`HUMAN_REVIEW_REQUIRED`. Una regla no implementada que devolviera `CONTINUE`
dejaría pasar mercancías que necesitaban justo esa regla, y el resultado sería
una clasificación equivocada con apariencia de fundada. Escalar es correcto;
pasar de largo, no.
"""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any, Protocol

from core.rgi_engine.pregunta import formular
from core.rgi_engine.results import RGIResult
from core.rgi_engine.states import RGIStatus

if TYPE_CHECKING:
    from collections.abc import Sequence

    from core.rgi_engine.context import ClassificationContext, TariffCandidate
    from core.rgi_engine.ports import Interpreter, LegalNotes, TariffCatalog


class RGIRule(Protocol):
    """Interfaz común de §17: `RGIRule.evaluate(context) -> RGIResult`."""

    rule_id: str

    def evaluate(
        self,
        context: ClassificationContext,
        *,
        candidates: Sequence[TariffCandidate],
        catalog: TariffCatalog,
        notes: LegalNotes,
        interpreter: Interpreter | None = None,
    ) -> RGIResult: ...


# ── RGI 1 ────────────────────────────────────────────────────────────────────


class RGI1:
    """Los textos de las partidas y las notas de sección o capítulo.

    Es la regla que resuelve la mayoría de los casos, y la única que SIEMPRE se
    aplica. Los títulos de sección y capítulo son indicativos: no clasifican.

    Las notas de exclusión pesan más que el texto de la partida. Una nota que
    dice "este capítulo no comprende..." descarta la partida por completo, por
    muy bien que encaje el texto — y por eso se consultan antes de dar por
    buena ninguna coincidencia.
    """

    rule_id = "RGI-1"

    def evaluate(
        self,
        context: ClassificationContext,
        *,
        candidates: Sequence[TariffCandidate],
        catalog: TariffCatalog,
        notes: LegalNotes,
        interpreter: Interpreter | None = None,
    ) -> RGIResult:
        hechos = context.as_input_facts()

        terminos = list(context.search_terms)
        if not terminos and interpreter is not None:
            terminos = list(interpreter.suggest_terms(context=context))

        if not terminos:
            return RGIResult(
                rule_id=self.rule_id,
                status=RGIStatus.INSUFFICIENT_INFORMATION,
                input_facts=hechos,
                reasoning_summary=(
                    "No hay términos de nomenclatura con los que buscar en la tarifa, "
                    "y no se proporcionó intérprete para derivarlos de la descripción."
                ),
                missing_information=("search_terms", *context.missing_facts()),
            )

        encontrados = list(catalog.headings(on_date=context.operation_date, terms=terminos))

        # Las notas de exclusión se aplican antes que nada: descartan la
        # partida aunque el texto encaje.
        sobreviven: list[TariffCandidate] = []
        excluidas: list[str] = []
        # La materia de la ficha descarta igual que una nota: una mercancía que
        # consta de acero no puede clasificarse en «las demás manufacturas de
        # plástico». Sin esto, la tubería de acero del corpus llegaba a la RGI
        # 3 c) con la 3926 todavía en la lista.
        familia = _familia_de_la_mercancia(context)
        for c in encontrados:
            nota = notes.excludes(on_date=context.operation_date, heading=c.heading, terms=terminos)
            if nota:
                excluidas.append(f"{c.code} excluida por nota: {nota}")
                continue
            materia = _material_contradice(c, familia)
            if materia:
                excluidas.append(
                    f"{c.code} descartada: su texto es de {materia} y la ficha declara {familia}"
                )
                continue
            sobreviven.append(c)

        fuentes = tuple(c.source_id for c in sobreviven if c.source_id is not None)
        razon_exclusiones = ("  Exclusiones: " + " · ".join(excluidas)) if excluidas else ""

        if not sobreviven:
            return RGIResult(
                rule_id=self.rule_id,
                status=RGIStatus.INSUFFICIENT_INFORMATION,
                input_facts=hechos,
                reasoning_summary=(
                    f"Ninguna partida vigente al {context.operation_date.isoformat()} "
                    f"comprende la mercancía con los términos {terminos}." + razon_exclusiones
                ),
                missing_information=context.missing_facts() or ("descripción más precisa",),
            )

        if len(sobreviven) == 1:
            c = sobreviven[0]
            return RGIResult(
                rule_id=self.rule_id,
                status=RGIStatus.RESOLVED,
                input_facts=hechos,
                candidate_codes=(c,),
                reasoning_summary=(
                    f"El texto de la partida {c.code} comprende la mercancía: "
                    f"«{c.text}». Ninguna nota de sección o capítulo la excluye."
                    + razon_exclusiones
                ),
                source_ids=fuentes,
                confidence=_confianza(context),
            )

        return RGIResult(
            rule_id=self.rule_id,
            status=RGIStatus.CONTINUE,
            input_facts=hechos,
            candidate_codes=tuple(sobreviven),
            reasoning_summary=(
                f"{len(sobreviven)} partidas comprenden la mercancía "
                f"({', '.join(c.code for c in sobreviven)}). "
                f"La RGI 1 no la resuelve; se continúa." + razon_exclusiones
            ),
            source_ids=fuentes,
        )


# ── RGI 2 ────────────────────────────────────────────────────────────────────

_INCOMPLETO = re.compile(
    r"\b(incompleto|sin\s+terminar|sin\s+montar|desmontad[oa]|desarmad[oa]|"
    r"kit|para\s+ensamblar|CKD|SKD)\b",
    re.IGNORECASE,
)
_MEZCLA = re.compile(
    r"\b(mezcla|mezclad[oa]|aleaci[oó]n|compuest[oa]\s+de|surtido)\b", re.IGNORECASE
)


class RGI2:
    """Artículos incompletos o sin terminar (a) y materias mezcladas (b).

    NO IMPLEMENTADA en v0.1. Detecta si sus precondiciones se cumplen y escala.

    Aplicarla bien exige juzgar si un artículo incompleto "presenta las
    características esenciales del artículo completo", que es un juicio
    material, no textual. Fingir que se resuelve sería peor que admitir que no.
    """

    rule_id = "RGI-2"

    def evaluate(
        self,
        context: ClassificationContext,
        *,
        candidates: Sequence[TariffCandidate],
        catalog: TariffCatalog,
        notes: LegalNotes,
        interpreter: Interpreter | None = None,
    ) -> RGIResult:
        texto = " ".join([context.description, *(f.value or "" for f in context.known_facts())])
        incompleto = _INCOMPLETO.search(texto)
        mezcla = _MEZCLA.search(texto)

        if not incompleto and not mezcla:
            return RGIResult(
                rule_id=self.rule_id,
                status=RGIStatus.CONTINUE,
                input_facts=context.as_input_facts(),
                candidate_codes=tuple(candidates),
                reasoning_summary=(
                    "La mercancía no se presenta incompleta, sin terminar ni desmontada, "
                    "y no consta que sea una mezcla o asociación de materias."
                ),
            )

        motivo = (
            f"presenta indicios de artículo incompleto o sin montar («{incompleto.group()}»)"
            if incompleto
            else f"presenta indicios de mezcla o asociación de materias («{mezcla.group()}»)"  # type: ignore[union-attr]
        )
        return RGIResult(
            rule_id=self.rule_id,
            status=RGIStatus.HUMAN_REVIEW_REQUIRED,
            input_facts=context.as_input_facts(),
            candidate_codes=tuple(candidates),
            reasoning_summary=(
                f"La mercancía {motivo}, así que la RGI 2 es aplicable. "
                f"Esta versión del motor no la implementa: determinar si presenta "
                f"las características esenciales del artículo completo requiere un "
                f"juicio material que no se puede derivar del texto. Requiere "
                f"revisión humana."
            ),
            missing_information=("aplicación de la RGI 2 por un clasificador",),
        )


# ── RGI 3 ────────────────────────────────────────────────────────────────────


class RGI3A:
    """La partida con la descripción más específica (RGI 3 a).

    "Más específica" es la que describe la mercancía por su nombre frente a la
    que la describe por su género. `specificity` lo aporta el catálogo, porque
    depende de los textos concretos y no de una heurística del motor.

    Un empate no se rompe aquí: se pasa a la 3 b), que es lo que manda la
    propia regla.
    """

    rule_id = "RGI-3a"

    def evaluate(
        self,
        context: ClassificationContext,
        *,
        candidates: Sequence[TariffCandidate],
        catalog: TariffCatalog,
        notes: LegalNotes,
        interpreter: Interpreter | None = None,
    ) -> RGIResult:
        hechos = context.as_input_facts()
        if len(candidates) < 2:
            return RGIResult(
                rule_id=self.rule_id,
                status=RGIStatus.CONTINUE,
                input_facts=hechos,
                candidate_codes=tuple(candidates),
                reasoning_summary="No hay concurrencia de partidas que resolver.",
            )

        # Primero, la partida que fija un umbral medible QUE LA MERCANCÍA
        # CUMPLE. Es más específica en el sentido que importa: el texto legal
        # dice algo comprobable y la ficha lo comprueba. Contar calificativos
        # —que es lo que hace `specificity`— no distingue una tubería de acero
        # de un artículo de grifería, y en el corpus elegía grifería.
        cumplen = [c for c in candidates if (lambda t: t[0] and not t[1])(_condiciones(c, context))]
        if len(cumplen) == 1:
            c = cumplen[0]
            otras = [o for o in candidates if o.code != c.code]
            return RGIResult(
                rule_id=self.rule_id,
                status=RGIStatus.RESOLVED,
                input_facts=hechos,
                candidate_codes=(c,),
                reasoning_summary=(
                    f"La partida {c.code} («{c.text}») fija una condición medible que la "
                    f"mercancía cumple, y {', '.join(o.code for o in otras)} no. La RGI 3 a) "
                    f"la prefiere por describirla de forma más específica."
                ),
                source_ids=tuple(x.source_id for x in (c,) if x.source_id is not None),
                confidence=_confianza(context),
            )

        maximo = max(c.specificity for c in candidates)
        mas_especificas = [c for c in candidates if c.specificity == maximo]

        if len(mas_especificas) == 1 and maximo > 0:
            c = mas_especificas[0]
            otras = [o for o in candidates if o.code != c.code]
            return RGIResult(
                rule_id=self.rule_id,
                status=RGIStatus.RESOLVED,
                input_facts=hechos,
                candidate_codes=(c,),
                reasoning_summary=(
                    f"La partida {c.code} («{c.text}») describe la mercancía de forma "
                    f"más específica que {', '.join(o.code for o in otras)}."
                ),
                source_ids=tuple(c.source_id for c in (c,) if c.source_id is not None),
                confidence=_confianza(context),
            )

        return RGIResult(
            rule_id=self.rule_id,
            status=RGIStatus.CONTINUE,
            input_facts=hechos,
            candidate_codes=tuple(candidates),
            reasoning_summary=(
                f"Las partidas {', '.join(c.code for c in mas_especificas)} son igual de "
                f"específicas; la RGI 3 a) no las distingue."
            ),
        )


class RGI3B:
    """La materia o el componente que confiere el carácter esencial (RGI 3 b).

    Es un juicio material, no textual, así que requiere `Interpreter`. Sin él,
    el motor NO adivina: escala a revisión humana.

    Y aunque haya intérprete, el modelo sólo propone: la máquina exige que su
    propuesta esté entre los candidatos reales de la tarifa. Un modelo que
    devuelva un código inventado no puede resolver nada.
    """

    rule_id = "RGI-3b"

    def evaluate(
        self,
        context: ClassificationContext,
        *,
        candidates: Sequence[TariffCandidate],
        catalog: TariffCatalog,
        notes: LegalNotes,
        interpreter: Interpreter | None = None,
    ) -> RGIResult:
        hechos = context.as_input_facts()
        if len(candidates) < 2:
            return RGIResult(
                rule_id=self.rule_id,
                status=RGIStatus.CONTINUE,
                input_facts=hechos,
                candidate_codes=tuple(candidates),
                reasoning_summary="No hay concurrencia de partidas que resolver.",
            )

        if interpreter is None:
            return RGIResult(
                rule_id=self.rule_id,
                status=RGIStatus.CONTINUE,
                input_facts=hechos,
                candidate_codes=tuple(candidates),
                reasoning_summary=(
                    "Determinar el carácter esencial exige un juicio material sobre la "
                    "mercancía y no hay intérprete disponible. Se continúa a la RGI 3 c)."
                ),
            )

        propuesta = interpreter.essential_character(context=context, candidates=candidates)
        if propuesta is None:
            return RGIResult(
                rule_id=self.rule_id,
                status=RGIStatus.CONTINUE,
                input_facts=hechos,
                candidate_codes=tuple(candidates),
                reasoning_summary=(
                    "No se pudo determinar qué componente confiere el carácter esencial."
                ),
            )

        codigo, razonamiento = propuesta
        elegido = next((c for c in candidates if c.code == codigo), None)
        if elegido is None:
            # El modelo devolvió algo que no está en la tarifa. Es exactamente
            # lo que la máquina existe para atrapar (§36).
            return RGIResult(
                rule_id=self.rule_id,
                status=RGIStatus.HUMAN_REVIEW_REQUIRED,
                input_facts=hechos,
                candidate_codes=tuple(candidates),
                reasoning_summary=(
                    f"El intérprete propuso la partida {codigo}, que no está entre los "
                    f"candidatos vigentes ({', '.join(c.code for c in candidates)}). "
                    f"No se acepta un código que no proviene de la tarifa."
                ),
                missing_information=("verificación del carácter esencial",),
            )

        return RGIResult(
            rule_id=self.rule_id,
            status=RGIStatus.RESOLVED,
            input_facts=hechos,
            candidate_codes=(elegido,),
            reasoning_summary=(
                f"El carácter esencial corresponde a {elegido.code} («{elegido.text}»). "
                f"{razonamiento}"
            ),
            source_ids=tuple(c.source_id for c in (elegido,) if c.source_id is not None),
            confidence=_confianza(context, penalizacion=Decimal("0.15")),
        )


class RGI3C:
    """La última partida por orden de numeración (RGI 3 c).

    Es el desempate de último recurso, y se aplica sólo cuando las anteriores
    no resolvieron. Resuelve, pero con confianza reducida y marcando revisión:
    llegar hasta aquí significa que ninguna razón sustantiva distinguió los
    candidatos, y eso conviene que lo vea un humano.
    """

    rule_id = "RGI-3c"

    def evaluate(
        self,
        context: ClassificationContext,
        *,
        candidates: Sequence[TariffCandidate],
        catalog: TariffCatalog,
        notes: LegalNotes,
        interpreter: Interpreter | None = None,
    ) -> RGIResult:
        hechos = context.as_input_facts()
        if len(candidates) < 2:
            return RGIResult(
                rule_id=self.rule_id,
                status=RGIStatus.CONTINUE,
                input_facts=hechos,
                candidate_codes=tuple(candidates),
                reasoning_summary="No hay concurrencia de partidas que resolver.",
            )

        ultima = max(candidates, key=lambda c: c.code)
        return RGIResult(
            rule_id=self.rule_id,
            status=RGIStatus.RESOLVED,
            input_facts=hechos,
            candidate_codes=(ultima,),
            reasoning_summary=(
                f"Ninguna regla anterior distinguió entre "
                f"{', '.join(sorted(c.code for c in candidates))}. Se aplica la última "
                f"por orden de numeración: {ultima.code}. Conviene revisión humana, "
                f"porque el desempate no responde a una razón sustantiva."
            ),
            source_ids=tuple(c.source_id for c in (ultima,) if c.source_id is not None),
            confidence=_confianza(context, penalizacion=Decimal("0.30")),
            # Resuelve, y aun así lo tiene que ver alguien. Hasta ahora esto
            # sólo estaba dicho en el `reasoning_summary` de arriba, que nadie
            # lee en tiempo de ejecución: la clasificación salía RESOLVED y sin
            # marcar. La confianza baja no bastaba, porque nada la usa de
            # umbral.
            requires_human_review=True,
        )


# ── RGI 4 y 5 ────────────────────────────────────────────────────────────────


class RGI4:
    """Las mercancías más análogas.

    NO IMPLEMENTADA. Si la secuencia llega aquí, es que ninguna partida
    comprende la mercancía y hay que buscar analogía — un juicio que esta
    versión no hace. Escala.
    """

    rule_id = "RGI-4"

    def evaluate(
        self,
        context: ClassificationContext,
        *,
        candidates: Sequence[TariffCandidate],
        catalog: TariffCatalog,
        notes: LegalNotes,
        interpreter: Interpreter | None = None,
    ) -> RGIResult:
        return RGIResult(
            rule_id=self.rule_id,
            status=RGIStatus.HUMAN_REVIEW_REQUIRED,
            input_facts=context.as_input_facts(),
            candidate_codes=tuple(candidates),
            reasoning_summary=(
                "Las reglas 1 a 3 no resolvieron la clasificación. La RGI 4 exige "
                "identificar la mercancía más análoga, juicio que esta versión del "
                "motor no realiza."
            ),
            missing_information=("aplicación de la RGI 4 por un clasificador",),
        )


_ESTUCHE = re.compile(
    r"\b(estuche|funda|maletín|caja|envase|recipiente|acondicionad[oa]\s+para\s+la\s+venta)\b",
    re.IGNORECASE,
)


class RGI5:
    """Estuches, envases y continentes similares.

    NO IMPLEMENTADA. Detecta la precondición y escala en vez de ignorarla: si
    la mercancía viene en un estuche que debe seguir la suerte del contenido,
    clasificar sin aplicar esta regla da un resultado equivocado.
    """

    rule_id = "RGI-5"

    def evaluate(
        self,
        context: ClassificationContext,
        *,
        candidates: Sequence[TariffCandidate],
        catalog: TariffCatalog,
        notes: LegalNotes,
        interpreter: Interpreter | None = None,
    ) -> RGIResult:
        hallazgo = _ESTUCHE.search(context.description)
        if not hallazgo:
            return RGIResult(
                rule_id=self.rule_id,
                status=RGIStatus.CONTINUE,
                input_facts=context.as_input_facts(),
                candidate_codes=tuple(candidates),
                reasoning_summary="No consta estuche, envase ni continente similar.",
            )
        return RGIResult(
            rule_id=self.rule_id,
            status=RGIStatus.HUMAN_REVIEW_REQUIRED,
            input_facts=context.as_input_facts(),
            candidate_codes=tuple(candidates),
            reasoning_summary=(
                f"La descripción menciona «{hallazgo.group()}», así que la RGI 5 puede "
                f"ser aplicable. Esta versión del motor no la implementa."
            ),
            missing_information=("aplicación de la RGI 5 por un clasificador",),
        )


# ── RGI 6 ────────────────────────────────────────────────────────────────────


class RGI6:
    """Clasificación a nivel de subpartida.

    Sólo se comparan subpartidas del mismo nivel, y se aplican las reglas
    anteriores *mutatis mutandis*. Es la regla que lleva de la partida de 4
    dígitos a la subpartida de 6 y, en México, a la fracción de 8.

    Cuando queda más de un candidato, esta versión NO elige: escala. Preferir
    revisión humana a una fracción inventada es lo que exige el §8.2, y una
    fracción equivocada cambia el arancel que paga un importador.
    """

    rule_id = "RGI-6"

    def evaluate(
        self,
        context: ClassificationContext,
        *,
        candidates: Sequence[TariffCandidate],
        catalog: TariffCatalog,
        notes: LegalNotes,
        interpreter: Interpreter | None = None,
    ) -> RGIResult:
        hechos = context.as_input_facts()
        if len(candidates) != 1:
            return RGIResult(
                rule_id=self.rule_id,
                status=RGIStatus.HUMAN_REVIEW_REQUIRED,
                input_facts=hechos,
                candidate_codes=tuple(candidates),
                reasoning_summary=(
                    "La RGI 6 requiere una partida determinada para descender a "
                    "subpartida, y no la hay."
                ),
            )

        partida = candidates[0]
        subs = list(catalog.subheadings(on_date=context.operation_date, heading=partida.heading))
        if not subs:
            return RGIResult(
                rule_id=self.rule_id,
                status=RGIStatus.INSUFFICIENT_INFORMATION,
                input_facts=hechos,
                candidate_codes=(partida,),
                reasoning_summary=(
                    f"No hay subpartidas cargadas para la partida {partida.heading} "
                    f"vigentes al {context.operation_date.isoformat()}."
                ),
                missing_information=(f"subpartidas de {partida.heading}",),
            )

        elegida = _unica_o_mas_especifica(subs, mercancia=context.description, context=context)
        if elegida is None:
            return RGIResult(
                rule_id=self.rule_id,
                status=RGIStatus.HUMAN_REVIEW_REQUIRED,
                input_facts=hechos,
                candidate_codes=tuple(subs),
                reasoning_summary=(
                    f"Varias subpartidas de {partida.heading} comprenden la mercancía "
                    f"({', '.join(s.code for s in subs)}) y ninguna es más específica. "
                    f"El motor no elige entre ellas."
                ),
                missing_information=("desempate de subpartida por un clasificador",),
                # La pregunta concreta, si hay una corta que lo resuelva. No
                # sustituye al aviso de arriba: lo acota.
                preguntas=tuple(formular(context, subs)),
            )

        fracciones = list(
            catalog.fractions(on_date=context.operation_date, subheading=elegida.code)
        )
        if not fracciones:
            return RGIResult(
                rule_id=self.rule_id,
                status=RGIStatus.RESOLVED,
                input_facts=hechos,
                candidate_codes=(elegida,),
                reasoning_summary=(
                    f"Subpartida {elegida.code} («{elegida.text}»). No hay fracciones "
                    f"cargadas por debajo."
                ),
                source_ids=tuple(c.source_id for c in (elegida,) if c.source_id is not None),
                confidence=_confianza(context),
            )

        # ── Descarte por contradicción ──────────────────────────────────────
        #
        # Antes de intentar elegir, se quitan las que la mercancía hace
        # imposibles: una fracción que dice «sin galvanizar» no puede ser la de
        # un cable que consta galvanizado. Descartar es una afirmación mucho
        # más barata de sostener que elegir, y se puede hacer sin saber cuál es
        # la correcta.
        #
        # LA REGLA QUE HACE ESTO SEGURO: descartar sólo puede RESOLVER cuando
        # queda exactamente una. Si quedan varias, se vuelve a la lista
        # COMPLETA y al desempate de siempre, no a los supervivientes.
        #
        # No es una cautela teórica. Con el cable 6x19 de ⌀10 mm, descartar
        # `73121008` («Sin galvanizar») y desempatar entre los supervivientes
        # por `specificity` daría `73121007` —«constituidos por 7 alambres»—
        # para una construcción de 114 alambres. Hoy el motor empata y se
        # niega, que es la respuesta correcta. Una mejora que convierte una
        # negativa honesta en una fracción equivocada no es una mejora.
        afirmado = _raices(
            " ".join([context.description, *(f.value or "" for f in context.known_facts())])
        )
        descartes = {
            c.code: m
            for c in fracciones
            if (m := _contradice(c, afirmado) or _lo_aprendido_la_descarta(c, context))
        }
        vivas = [c for c in fracciones if c.code not in descartes]
        # El motivo viene ya escrito de donde salga —negación del texto o
        # respuesta firmada— y se cita tal cual. Envolverlo en «el texto dice
        # "sin ..."» producía frases rotas en cuanto el descarte no venía de
        # una negación: «el texto dice "sin la ficha dice ..."».
        motivos = " · ".join(f"{c}: {m}" for c, m in descartes.items())

        if len(vivas) == 1:
            unica = vivas[0]
            return RGIResult(
                rule_id=self.rule_id,
                status=RGIStatus.RESOLVED,
                input_facts=hechos,
                candidate_codes=(unica,),
                reasoning_summary=(
                    f"Partida {partida.heading} → subpartida {elegida.code} → "
                    f"fracción {unica.code} («{unica.text}»). Es la única que la "
                    f"mercancía no contradice; descartadas: {motivos}."
                ),
                source_ids=tuple(
                    c.source_id for c in (partida, elegida, unica) if c.source_id is not None
                ),
                confidence=_confianza(context),
            )

        fraccion = _unica_o_mas_especifica(
            fracciones, mercancia=context.description, context=context
        )
        if fraccion is None:
            return RGIResult(
                rule_id=self.rule_id,
                status=RGIStatus.HUMAN_REVIEW_REQUIRED,
                input_facts=hechos,
                candidate_codes=tuple(vivas or fracciones),
                reasoning_summary=(
                    f"Varias fracciones de {elegida.code} son aplicables "
                    f"({', '.join(f.code for f in (vivas or fracciones))}). El motor no "
                    f"elige: una fracción equivocada cambia el arancel que paga el "
                    f"importador."
                    + (
                        f" Sí descartó {len(descartes)} por contradicción — {motivos}."
                        if descartes
                        else ""
                    )
                ),
                missing_information=("desempate de fracción por un clasificador",),
                preguntas=tuple(formular(context, list(vivas or fracciones))),
            )

        return RGIResult(
            rule_id=self.rule_id,
            status=RGIStatus.RESOLVED,
            input_facts=hechos,
            candidate_codes=(fraccion,),
            reasoning_summary=(
                f"Partida {partida.heading} → subpartida {elegida.code} → "
                f"fracción {fraccion.code} («{fraccion.text}»)."
            ),
            source_ids=tuple(
                c.source_id for c in (partida, elegida, fraccion) if c.source_id is not None
            ),
            confidence=_confianza(context),
        )


# ── Auxiliares ───────────────────────────────────────────────────────────────


#: Por debajo de esto una palabra no distingue nada: «de», «los», «para».
_MINIMO_DISTINTIVO = 5


def _plano(texto: str) -> str:
    """El texto sin acentos ni mayúsculas, para poder compararlo."""
    return unicodedata.normalize("NFKD", texto.casefold()).encode("ascii", "ignore").decode()


def _palabras(texto: str) -> set[str]:
    """Las palabras del texto que pueden distinguir, sin acentos ni mayúsculas."""
    return {p for p in re.findall(r"[^\W\d_]+", _plano(texto)) if len(p) >= _MINIMO_DISTINTIVO}


#: Prefijo con el que se comparan dos palabras para decidir que hablan de lo
#: mismo. Seis, medido contra los pares que importan:
#:
#:     soldadura / soldada        6 ✓   7 ✗   ← costó 11 clasificaciones
#:     galvanizar / galvanizado   6 ✓   7 ✓
#:     acero / acerado            6 ✗   7 ✗   ← el que NO debe casar
#:
#: Estaba en siete y por eso la 7304 —«Tubos y perfiles huecos, SIN SOLDADURA»—
#: no se descartaba para una tubería SOLDADA: `soldadu` no es `soldada`. Por
#: una letra, el motor clasificó once tubos soldados como tubos sin costura.
#:
#: Cinco sería demasiado: casaría «recubrimiento» con «recubierto», que a veces
#: son lo mismo y a veces no, y este umbral sólo debe casar lo indudable.
_RAIZ = 6

#: «sin X» niega X. «con o sin X» NO lo niega: lo permite en los dos sentidos,
#: y tratarlo como negación descartaría la fracción correcta de un cable
#: lubricado por decir su texto «con o sin lubricación».
_NIEGA = re.compile(r"(?<!con o )\bsin\s+([^\W\d_]+)")


def _raices(texto: str) -> set[str]:
    """Las raíces de las palabras distintivas de un texto."""
    return {p[:_RAIZ] for p in _palabras(texto)}


def _contradice(candidata: TariffCandidate, afirmado: set[str]) -> str | None:
    """La palabra por la que esta candidata es imposible, o `None`.

    Descartar es más seguro que elegir: una fracción que dice «sin galvanizar»
    no puede ser la de una mercancía que consta galvanizada, y eso se afirma
    sin saber cuál ES la correcta.

    Sólo mira negaciones explícitas del texto legal contra lo que el documento
    AFIRMA de la mercancía. No deduce: que una mercancía no mencione una
    característica no significa que no la tenga, y tratar el silencio como
    negación descartaría la correcta.
    """
    # Sobre el texto NORMALIZADO: la tarifa escribe «Sin galvanizar» con
    # mayúscula inicial y «diámetro» con acento, y un patrón que no lo
    # contemple no encuentra ni una sola negación.
    for negada in _NIEGA.findall(_plano(candidata.text)):
        negada = str(negada)
        raices = _raices(negada)
        if raices and raices & afirmado:
            return f"el texto dice «sin {negada}»"
    return None


#: Familias de materia que se excluyen entre sí. Una mercancía de acero no es
#: de plástico, y eso se puede afirmar sin saber cuál es su partida.
#:
#: Es vocabulario, no criterio jurídico: no decide qué partida corresponde,
#: sólo cuáles son imposibles. Deliberadamente corto — cada entrada de más es
#: una forma nueva de descartar la partida correcta.
_FAMILIAS: dict[str, frozenset[str]] = {
    "ferroso": frozenset({"acero", "aceros", "hierro", "fundicion"}),
    "aluminio": frozenset({"aluminio"}),
    "cobre": frozenset({"cobre", "laton", "bronce"}),
    "plastico": frozenset({"plastico", "plasticos", "polimero", "polimeros"}),
    "caucho": frozenset({"caucho"}),
    "ceramica": frozenset({"ceramica", "ceramicas", "porcelana"}),
    "vidrio": frozenset({"vidrio"}),
    "madera": frozenset({"madera"}),
    "papel": frozenset({"papel", "carton"}),
}


def _familias(texto: str) -> set[str]:
    """Qué familias de materia nombra un texto."""
    palabras = set(re.findall(r"[^\W\d_]+", _plano(texto)))
    return {f for f, terminos in _FAMILIAS.items() if terminos & palabras}


def _familia_de_la_mercancia(context: ClassificationContext) -> str | None:
    """La familia de materia que DECLARA la ficha, o `None`.

    Sólo de un hecho sólido cuyo nombre hable de materia —`material`,
    `chassis_material`—, nunca de la descripción comercial. Un cable de acero
    con alma de fibra menciona dos materias en su descripción, y adivinar cuál
    manda descartaría la partida correcta.

    `None` si no consta o si la ficha nombra dos familias: entonces no hay una
    afirmación contra la que contradecir.
    """
    vistas: set[str] = set()
    for hecho in context.facts:
        if not hecho.is_solid or "material" not in hecho.name.casefold():
            continue
        vistas |= _familias(hecho.value or "")
    return next(iter(vistas)) if len(vistas) == 1 else None


def _material_contradice(candidata: TariffCandidate, familia: str | None) -> str | None:
    """La materia por la que esta candidata es imposible, o `None`.

    Sólo descarta cuando la candidata nombra materia Y NINGUNA de las que
    nombra es la de la mercancía. Una partida que nombra las dos —«de
    plástico reforzado con acero»— no contradice nada.
    """
    if familia is None:
        return None
    nombradas = _familias(candidata.text)
    if not nombradas or familia in nombradas:
        return None
    return ", ".join(sorted(nombradas))


#: Una condición medible del texto legal: «diámetro exterior superior a 406.4
#: mm». Tres partes — de qué habla, en qué sentido, y contra qué número.
_CONDICION = re.compile(
    r"([^\W\d_][^,;:()]{2,40}?)\s+"
    r"(superior a|mayor de|mayor a|inferior a|menor de|menor o igual a|superior o igual a)\s+"
    r"(\d+(?:[.,]\d+)?)",
)

#: Cómo se compara según el sentido. `True` = la mercancía CUMPLE la condición.
_SENTIDOS: dict[str, Any] = {
    "superior a": lambda v, u: v > u,
    "mayor de": lambda v, u: v > u,
    "mayor a": lambda v, u: v > u,
    "superior o igual a": lambda v, u: v >= u,
    "inferior a": lambda v, u: v < u,
    "menor de": lambda v, u: v < u,
    "menor o igual a": lambda v, u: v <= u,
}


def _numero(valor: str) -> Decimal | None:
    """El valor de un hecho como número, si lo es."""
    try:
        return Decimal(valor.strip().replace(",", "."))
    except (InvalidOperation, AttributeError):
        return None


#: Sufijos de unidad en los nombres de atributo. No distinguen de qué habla el
#: atributo, sólo en qué se mide, así que no entran en el emparejamiento.
_UNIDADES = frozenset({"mm", "cm", "kg", "gr", "ml", "pulgadas", "grados", "watts", "volts"})


def _hecho_de(context: ClassificationContext, sujeto: str) -> Decimal | None:
    """El valor numérico del hecho del que habla `sujeto`, o `None`.

    Empareja «diámetro exterior superior a 406.4 mm» con `diametro_exterior_mm`
    pidiendo que las palabras DISTINTIVAS del atributo —su nombre sin la
    unidad— estén todas en el sujeto.

    Y si encajan DOS atributos, no cuenta ninguno: con `diametro_mm` y
    `diametro_exterior_mm` en la misma ficha, un sujeto que dice «diámetro
    exterior» los admite a los dos, y elegir uno compararía el umbral legal
    contra una medida distinta de la que nombra. Misma disciplina que en todo
    lo demás: ante la duda, no se decide.
    """
    palabras = set(re.findall(r"[^\W\d_]+", _plano(sujeto)))
    candidatos: list[Decimal] = []
    for hecho in context.facts:
        if not hecho.is_solid:
            continue
        nombre = set(re.findall(r"[^\W\d_]+", _plano(hecho.name))) - _UNIDADES
        valor = _numero(hecho.value or "")
        if nombre and nombre <= palabras and valor is not None:
            candidatos.append(valor)
    return candidatos[0] if len(candidatos) == 1 else None


def _condiciones(candidata: TariffCandidate, context: ClassificationContext) -> tuple[int, int]:
    """(cumplidas, incumplidas) de las condiciones medibles de esta candidata.

    Una condición que no se puede evaluar —porque la ficha no trae ese dato—
    no cuenta como ninguna de las dos. El silencio de la ficha no cumple ni
    incumple nada.
    """
    cumplidas = incumplidas = 0
    for sujeto, sentido, umbral in _CONDICION.findall(_plano(candidata.text)):
        valor = _hecho_de(context, sujeto)
        limite = _numero(umbral)
        if valor is None or limite is None:
            continue
        if _SENTIDOS[sentido](valor, limite):
            cumplidas += 1
        else:
            incumplidas += 1
    return cumplidas, incumplidas


def _lo_aprendido_la_descarta(
    candidata: TariffCandidate, context: ClassificationContext
) -> str | None:
    """¿Alguna exclusión aprendida hace imposible esta posición?

    Devuelve el motivo, para que la traza pueda citarlo: quien audite tiene que
    poder ver que se descartó por una respuesta firmada, no por un algoritmo.

    Es el mismo descarte por contradicción que ya hacía con las negaciones del
    texto («sin galvanizar»), con una diferencia: aquella la deducía del texto
    legal y ésta la sabe porque alguien la contestó. Por eso la traza las
    distingue — una se sostiene sola, la otra se sostiene en quien la firmó.
    """
    for de_la_ficha, de_la_tarifa in context.exclusiones:
        if _palabras(de_la_tarifa) & _palabras(candidata.text):
            return f"la ficha dice «{de_la_ficha}», que no es «{de_la_tarifa}»"
    return None


def _el_grupo_la_describe(candidata: TariffCandidate, mercancia: str) -> bool:
    """¿El encabezado de guion de esta posición habla de esta mercancía?

    SÓLO EL GRUPO, NO TODO EL TEXTO, Y HAY UNA RAZÓN CARA DETRÁS

    La primera versión miraba el texto entero y clasificó un cable de acero sin
    recubrimiento declarado en «De acero SIN RECUBRIMIENTO» — porque «acero»
    era la única palabra compartida. Afirmaba una ausencia que la ficha no
    dice, que es exactamente lo que el test del silencio existe para impedir.

    «Acero» lo dice media tarifa; que una posición no lo repita no significa
    que su mercancía no lo sea. El encabezado de guion es distinto: la LIGIE lo
    pone AHÍ PRECISAMENTE para separar hermanas —«Los demás monitores:» frente
    a «Proyectores:»— así que casar con él es casar con el discriminador que la
    propia nomenclatura eligió, no con una coincidencia de vocabulario.
    """
    if not candidata.group_text:
        return False
    return bool(_palabras(candidata.group_text) & _palabras(mercancia))


def _algo_la_sostiene(candidata: TariffCandidate, mercancia: str) -> bool:
    """¿Hay algo en la mercancía que respalde lo que esta candidata añade?

    Una candidata «más específica» lo es porque su TEXTO lleva calificativos,
    no porque la mercancía los cumpla. Si ninguno de ellos aparece en lo que
    consta del producto, elegirla es afirmar una característica que el
    documento no dice.
    """
    return bool(_palabras(candidata.text) & _palabras(mercancia))


def _unica_o_mas_especifica(
    cands: Sequence[TariffCandidate],
    *,
    mercancia: str = "",
    context: ClassificationContext | None = None,
) -> TariffCandidate | None:
    """El único candidato, o el más específico si algo de la mercancía lo sostiene.

    `None` significa que nadie puede decidir con lo que hay, y alguien tiene
    que hacerlo.

    LA ESPECIFICIDAD NO ES EVIDENCIA

    `specificity` mide cuántos calificativos tiene el TEXTO de la fracción, no
    que la mercancía los cumpla. Elegir por ella a secas hace que el motor
    afirme lo que el documento no dice.

    El caso que lo destapó (Persona 1, 28-sep, a partir de un dictamen
    humano): una vajilla de cerámica vidriada competía entre

        69120003  «De Talavera.»   specificity 2
        69120099  «Los demás.»     specificity 0

    y el motor elegía Talavera **cinco veces**, en una mercancía que no
    menciona Talavera en ninguna parte. El agente aduanal y la declaración
    coincidían en «Los demás».

    Ahora la más específica sólo gana si alguna de sus palabras distintivas
    aparece en la mercancía. Si no, se devuelve `None` y decide una persona:
    una fracción equivocada cambia el arancel que paga el importador.
    """
    if len(cands) == 1:
        return cands[0]

    # ── La única cuyo texto describe la mercancía ────────────────────────────
    #
    # Desde el ADR 0004 el texto de una subpartida llega con su nivel de un
    # guion delante: «Los demás monitores. Aptos para ser conectados
    # directamente…». Ese encabezado es lo que distingue a las nueve
    # subpartidas de 8528 —monitores CRT, los demás monitores, proyectores,
    # televisores— que antes decían casi lo mismo.
    #
    # Si EXACTAMENTE UNA comparte palabras distintivas con la mercancía, ésa
    # es la que la describe, y elegirla es una afirmación que se puede leer:
    # «la mercancía dice X y sólo esta posición dice X».
    #
    # Si la comparten varias, no se elige. Y si no la comparte ninguna,
    # tampoco. La regla de siempre: sólo resuelve cuando queda una.
    if mercancia:
        describen = [c for c in cands if _el_grupo_la_describe(c, mercancia)]
        if len(describen) == 1:
            return describen[0]

    # ── Antes que la especificidad: la condición que la mercancía CUMPLE ──
    #
    # YA SE USA TAMBIÉN AL BAJAR (1-oct). Antes no se podía, y la razón era
    # otra de la que parecía.
    #
    # El texto de una subpartida NO era suyo: `subheadings()` lo derivaba del
    # `min()` de las descripciones de sus fracciones, así que 730520 —«Tubos de
    # entubación (casing)»— le llegaba al motor como «Con espesor de pared
    # inferior a 50.8 mm», el texto de una hija. Con eso, la tubería del corpus
    # resolvía a 73052001 —tubos para extracción de petróleo— porque cumplía un
    # umbral prestado. Pasó de negarse honestamente a contestar mal.
    #
    # La causa no era este desempate: era aquel `min()`. Arreglado en origen —
    # cada nivel lee su propio texto de `tariff_headings` (ADR 0002)— la
    # condición numérica vuelve a ser una afirmación sobre la posición que la
    # declara, y se puede usar para bajar.
    #
    # Una partida que fija un umbral medible y la mercancía lo cumple es más
    # específica en el sentido que importa: el texto legal dice algo
    # comprobable y la ficha lo comprueba. Eso es una razón que un agente
    # aduanal firma; contar calificativos no lo es.
    #
    # El caso real: una tubería de acero de ⌀ 508 mm competía entre 7305
    # —«diámetro exterior superior a 406.4 mm, de hierro o acero»—, 7306 y 8481
    # —grifería—. Las tres empataban en especificidad y la RGI 3 c) elegía la
    # última por numeración: 8481. Grifería, para un tubo.
    #
    # Sólo gana si es la ÚNICA con condición cumplida. Con dos, decide una
    # persona: misma disciplina que el descarte por contradicción.
    if context is not None:
        con_condicion = [(c, _condiciones(c, context)) for c in cands]
        cumplen = [c for c, (ok, mal) in con_condicion if ok and not mal]
        if len(cumplen) == 1:
            return cumplen[0]

    maximo = max(c.specificity for c in cands)
    lideres = [c for c in cands if c.specificity == maximo]
    if len(lideres) != 1 or maximo <= 0:
        return None
    lider = lideres[0]
    return lider if _algo_la_sostiene(lider, mercancia) else None


def _confianza(context: ClassificationContext, *, penalizacion: Decimal = Decimal("0")) -> Decimal:
    """Confianza a partir de la solidez de los hechos, no de una corazonada.

    Se calcula sobre la proporción de hechos OBSERVED o EXTRACTED: una
    clasificación sostenida en datos inferidos por un modelo vale menos que una
    sostenida en la ficha técnica, y el número tiene que reflejarlo.

    `penalizacion` la aplican las reglas de desempate: llegar a la RGI 3 c)
    significa que ninguna razón sustantiva distinguió los candidatos.
    """
    total = len(context.facts)
    if total == 0:
        return max(Decimal("0.0000"), Decimal("0.5000") - penalizacion)
    solidos = sum(1 for f in context.facts if f.is_solid)
    base = Decimal("0.5000") + (Decimal(solidos) / Decimal(total)) * Decimal("0.5000")
    return max(Decimal("0.0000"), min(Decimal("1.0000"), base - penalizacion)).quantize(
        Decimal("0.0001")
    )
