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
from decimal import Decimal
from typing import TYPE_CHECKING, Protocol

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
        for c in encontrados:
            nota = notes.excludes(on_date=context.operation_date, heading=c.heading, terms=terminos)
            if nota:
                excluidas.append(f"{c.code} excluida por nota: {nota}")
            else:
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

        elegida = _unica_o_mas_especifica(subs)
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

        fraccion = _unica_o_mas_especifica(fracciones)
        if fraccion is None:
            return RGIResult(
                rule_id=self.rule_id,
                status=RGIStatus.HUMAN_REVIEW_REQUIRED,
                input_facts=hechos,
                candidate_codes=tuple(fracciones),
                reasoning_summary=(
                    f"Varias fracciones de {elegida.code} son aplicables "
                    f"({', '.join(f.code for f in fracciones)}). El motor no elige: una "
                    f"fracción equivocada cambia el arancel que paga el importador."
                ),
                missing_information=("desempate de fracción por un clasificador",),
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


def _unica_o_mas_especifica(cands: Sequence[TariffCandidate]) -> TariffCandidate | None:
    """El único candidato, o el más específico si no hay empate.

    `None` significa que hay empate y alguien tiene que decidir.
    """
    if len(cands) == 1:
        return cands[0]
    maximo = max(c.specificity for c in cands)
    lideres = [c for c in cands if c.specificity == maximo]
    return lideres[0] if len(lideres) == 1 and maximo > 0 else None


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
