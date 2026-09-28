"""Harness de hs_accuracy (§39): la única medición que no depende de nosotros.

Toma casos con clasificación conocida —rulings del SA 2022—, le da al motor
SÓLO la descripción de la mercancía, y compara los seis primeros dígitos de lo
que concluye contra el HS6 del ruling.

CUATRO REGLAS QUE DECIDEN SI EL NÚMERO VALE ALGO (Persona 1, 14-sep)

1. **No persiste.** Este módulo no conoce la base: recibe dos funciones y
   devuelve un reporte. Quien lo conecte a Postgres lo hace con una sesión de
   sólo lectura (`apps.evaluacion`). Una evaluación que escribiera en
   `classification_decisions` ensuciaría la métrica de producción, como ya lo
   hizo una prueba el 9 de septiembre.

2. **Sin fugas.** Al extractor le llega un `SourceDocument` construido sólo con
   la descripción; al clasificador, el Product DNA y la fecha. El HS6 esperado,
   el razonamiento y la clasificación del ruling no viajan por ningún
   parámetro. Y si la descripción misma contiene el HS6 esperado, el caso se
   excluye como POSIBLE_FUGA: la respuesta estaría en la pregunta.

3. **Seis dígitos, SA 2022.** Se compara `codigo[:6]` con el HS6. Un caso de
   otra nomenclatura, o con un HS6 que no son seis dígitos, se excluye y se
   cuenta — nunca se adapta.

   CON UNA EXCEPCIÓN, Y NO ES UNA GRIETA: `mismo_catalogo_a_la_fecha`.

   El filtro de nomenclatura protege de comparar un HTS10 de Estados Unidos
   contra la TIGIE: dos nomenclaturas distintas, dos cosas que no se tocan.
   Pero cuando la verdad de un caso SALE DEL MISMO CATÁLOGO que el motor
   consulta, y a la MISMA FECHA, la comparación es válida por construcción y
   no hace falta afirmar ninguna edición del Sistema Armonizado.

   La fecha no es un adorno. Comparar una verdad construida contra la LIGIE de
   2024 con una clasificación de 2026 sería inválido aunque las dos fueran
   TIGIE: es la regla 5 y es innegociable. Ya se cumple por construcción —el
   caso lleva su fecha y el harness llama `clasificar(dna, caso.fecha)`, así
   que las dos partes leen el catálogo vigente ese día— y por eso el campo
   NOMBRA esa condición en vez de decir «misma nomenclatura» a secas. Si
   alguien construye mañana una fuente cuya verdad venga de otra fecha, el
   nombre del campo le dirá que está mintiendo.

   POR QUÉ SE QUITÓ «HS2022» DE LA FUENTE DEL CORPUS, PARA QUE NADIE LO
   VUELVA A PONER: porque no se podía citar. Persona 2 verificó las 893
   páginas de la LIGIE 2022 y el decreto del DOF del 7-jun-2022: ni el
   Artículo 1 ni el preámbulo mencionan el Sistema Armonizado, ninguna
   enmienda, ninguna edición. El Artículo 1 sólo dice «de conformidad con la
   siguiente TARIFA». Afirmar SA 2022 en el código era conocimiento nuestro
   presentado como hecho verificable, que es justo lo que la regla 1 prohíbe.
   Y para esta medición no sostenía nada: la verdad del corpus y el motor
   leen la misma tabla el mismo día.

   `NOMENCLATURA_ADMITIDA = "HS2022"` se queda para las fuentes externas.
   Cuando llegue CBP CROSS, ese filtro protege algo real, y la fuente citable
   será el Convenio de la OMA — no la LIGIE.

4. **Cuesta dinero.** `estimar_costo` antes de correr; el reporte trae el costo
   real de lo que sí se llamó. Todo en Decimal: lo calcula este código, no un
   modelo.

LO QUE EL NÚMERO NO DICE

`hs_accuracy` se calcula sobre los casos EVALUADOS, y un
INSUFFICIENT_INFORMATION cuenta como no acierto: el motor no dio el código. Por
eso el reporte trae además `acierto_cuando_responde` y las tasas de
INSUFFICIENT_INFORMATION, de desempate por RGI 3 c) y de degradación a
búsqueda por término. Un 40 % con 50 % de insuficientes y un 40 % con 0 % son
motores muy distintos, y el número solo no los separa.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field

from core.evaluation.intervalos import wilson
from core.product_dna.types import ProductDnaDraft, SourceDocument

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

#: La única nomenclatura contra la que se compara (regla 3).
NOMENCLATURA_ADMITIDA: Final = "HS2022"

#: La regla de desempate de último recurso. Mismo criterio de normalización que
#: la bandeja: `RGI-3c`, `RGI3C` y `rgi 3 c` son la misma regla.
_RGI_3C: Final = "RGI3C"

_MILLON: Final = Decimal(1_000_000)
_CIEN: Final = Decimal(100)
_DOS: Final = Decimal("0.01")

Motivo = Literal[
    "NOMENCLATURA_NO_SA2022",
    "HS6_INVALIDO",
    "POSIBLE_FUGA",
    "FUERA_DE_VIGENCIA_DEL_CATALOGO",
]


class CasoDeEvaluacion(BaseModel):
    """Un caso con verdad conocida. Lo entrega un adaptador (`FuenteDeCasos`)."""

    model_config = ConfigDict(frozen=True)

    identificador: str
    """Id del ruling en su fuente. Para auditar, NUNCA para el motor."""
    descripcion: str
    """Lo único que llega al motor."""
    hs6_esperado: str
    fecha: date
    fuente: str
    nomenclatura: str
    data_origin: str
    """OFFICIAL/PUBLIC para rulings reales; SYNTHETIC en pruebas (§33)."""

    mismo_catalogo_a_la_fecha: bool = False
    """La verdad de este caso y el motor leen el MISMO catálogo a la MISMA fecha.

    Cuando es cierto, el filtro de nomenclatura no aplica: comparar los seis
    primeros dígitos es comparar la misma tabla contra sí misma, y no hace
    falta afirmar ninguna edición del Sistema Armonizado para justificarlo.

    Las dos mitades importan. «Mismo catálogo» sin «misma fecha» no basta: una
    verdad construida contra la LIGIE de 2024 no se puede comparar con una
    clasificación de 2026 aunque las dos sean TIGIE (regla 5). Aquí se cumple
    porque el caso lleva su fecha y el motor clasifica con ella.

    Es `False` por omisión: una fuente externa —un ruling de otro país— no
    cumple ninguna de las dos, y el que escriba un adaptador tiene que
    afirmarlo a propósito, no heredarlo.
    """

    verdad_de_modelo: bool = False
    """La clasificación esperada la decidió un MODELO, no una persona.

    No es lo mismo que `data_origin=SYNTHETIC`, y confundirlos es el error que
    esto existe para impedir. SYNTHETIC dice que el DATO es inventado; esto
    dice que el JUICIO contra el que se compara lo emitió otro modelo.

    Un caso así no mide precisión: mide COINCIDENCIA CON OTRO MODELO. Sigue
    sirviendo —los desacuerdos son justo donde hay que mirar— pero presentarlo
    como precisión sería afirmar que un modelo valida a otro.

    El corpus espejo v1 salió de una sesión de ChatGPT y no tuvo clasificador
    humano en el circuito (Persona 1, 23-sep-2026). Sus afirmaciones
    contrastables sí están verificadas contra la LIGIE oficial —fracción
    existente, NICO válido, tasa y UMC correctas, las ocho comprobaciones del
    #84 sobre 180 partidas, cero defectos—; lo que nadie comprobó es el JUICIO
    de clasificación.
    """


class UsoDeCaso(BaseModel):
    """Tokens consumidos por un caso, para el costo."""

    model_config = ConfigDict(frozen=True)

    entrada: int = 0
    salida: int = 0
    embedding: int = 0
    """Estimado: el proveedor no devuelve el consumo del embedding."""


class Tarifas(BaseModel):
    """Precios por millón de tokens, en USD, con su procedencia."""

    model_config = ConfigDict(frozen=True)

    entrada_por_mtok: Decimal
    salida_por_mtok: Decimal
    embedding_por_mtok: Decimal
    fuente: str
    """De dónde salieron. Una tarifa sin fuente es un número inventado."""


class ExtraccionConUso(BaseModel):
    """Lo que devuelve el extractor: el DNA y lo que costó."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    dna: ProductDnaDraft
    uso: UsoDeCaso = Field(default_factory=UsoDeCaso)


class Clasificacion(BaseModel):
    """Lo mínimo del resultado del motor que el harness necesita."""

    model_config = ConfigDict(frozen=True)

    codigo: str | None
    estado: str
    """RESOLVED · HUMAN_REVIEW_REQUIRED · INSUFFICIENT_INFORMATION."""
    rgi_path: tuple[str, ...] = ()
    uso_vectores: bool
    embedding_tokens: int = 0


class ResultadoDeCaso(BaseModel):
    """Qué pasó con un caso. Sin la descripción ni el razonamiento del ruling."""

    model_config = ConfigDict(frozen=True)

    identificador: str
    resultado: Literal["EVALUADO", "EXCLUIDO", "ERROR"]
    motivo: str | None = None
    hs6_esperado: str
    hs6_obtenido: str | None = None
    acierto: bool | None = None
    estado_motor: str | None = None
    llego_a_rgi_3c: bool = False
    degradado: bool = False
    uso: UsoDeCaso = Field(default_factory=UsoDeCaso)


class Acierto(BaseModel):
    aciertos: int = 0
    comparados: int = 0
    porcentaje: Decimal | None = None
    """`None` sin comparados: desconocido, no cero."""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def margen_95(self) -> Decimal | None:
        """Media anchura del intervalo de Wilson, en puntos.

        Un 100 % sobre un caso y un 100 % sobre ochenta se leen igual y no
        valen igual (Persona 1, 28-sep). Con un caso el margen sale tan ancho
        que descalifica el número solo, sin que quien lee tenga que acordarse
        de la n. Es el mismo criterio que ya usa la métrica de detección.
        """
        return wilson(self.aciertos, self.comparados)


class Reporte(BaseModel):
    """Resultado de una corrida. No se guarda en ninguna tabla."""

    fuente: str
    casos: int
    evaluados: int
    excluidos: dict[str, int] = Field(default_factory=dict)
    errores: int = 0

    hs_accuracy: Acierto = Field(default_factory=Acierto)
    """Sobre los evaluados. INSUFFICIENT_INFORMATION cuenta como no acierto."""
    acierto_cuando_responde: Acierto = Field(default_factory=Acierto)
    """Sólo sobre los casos en que el motor dio un código."""

    tasa_insuficiente: Decimal | None = None
    tasa_rgi_3c: Decimal | None = None
    tasa_degradacion: Decimal | None = None
    """Casos en que la búsqueda cayó a término por fallo o falta de proveedor."""

    costo_usd: Decimal = Decimal(0)
    tarifas_fuente: str

    es_simulacion: bool
    """Algún caso es SYNTHETIC: el número NO es una medición (§33)."""

    interrumpido: str | None = None
    """Por qué la corrida se cortó antes de tiempo, o `None` si llegó al final.

    Una corrida interrumpida NO es una corrida con menos casos: los que faltan
    son los ÚLTIMOS, no una muestra. El 23-sep la base del equipo se apagó a
    mitad de la medición y los 55 casos que quedaban eran los pedimentos
    600011 a 600015 — un trozo contiguo del corpus, no un azar. Un porcentaje
    calculado así se puede publicar, pero diciendo esto.
    """

    verdad_de_modelo: bool = False
    """Algún caso trae verdad decidida por un modelo: esto NO es precisión.

    El cuarto límite, con las mismas letras que los otros tres. Va en el
    reporte y no en una nota al pie porque un número que se presenta como
    precisión sin serlo hace más daño que no medir.
    """

    resultados: list[ResultadoDeCaso] = Field(default_factory=list)


def _normalizar_regla(rule_id: str) -> str:
    return "".join(c for c in rule_id if c.isalnum()).upper()


def _pct(parte: int, total: int) -> Decimal | None:
    if total == 0:
        return None
    return (Decimal(parte) / Decimal(total) * _CIEN).quantize(_DOS)


def _contiene_hs6(descripcion: str, hs6: str) -> bool:
    """¿La descripción trae el HS6 esperado? «847130», «8471.30» o «8471 30»."""
    patron = rf"(?<!\d){hs6[:4]}[\s.]?{hs6[4:]}(?!\d)"
    return re.search(patron, descripcion) is not None


def motivo_de_exclusion(caso: CasoDeEvaluacion, *, fecha_minima: date | None) -> Motivo | None:
    """Por qué un caso no puede medir nada. `None` si se puede evaluar."""
    if not caso.mismo_catalogo_a_la_fecha and caso.nomenclatura != NOMENCLATURA_ADMITIDA:
        return "NOMENCLATURA_NO_SA2022"
    if not re.fullmatch(r"\d{6}", caso.hs6_esperado):
        return "HS6_INVALIDO"
    if _contiene_hs6(caso.descripcion, caso.hs6_esperado):
        return "POSIBLE_FUGA"
    if fecha_minima is not None and caso.fecha < fecha_minima:
        # El catálogo no tenía tarifa vigente ese día: un fallo aquí mediría la
        # carga de datos, no al motor.
        return "FUERA_DE_VIGENCIA_DEL_CATALOGO"
    return None


def _costo(uso: UsoDeCaso, tarifas: Tarifas) -> Decimal:
    return (
        Decimal(uso.entrada) * tarifas.entrada_por_mtok
        + Decimal(uso.salida) * tarifas.salida_por_mtok
        + Decimal(uso.embedding) * tarifas.embedding_por_mtok
    ) / _MILLON


def estimar_costo(casos: int, *, uso_por_caso: UsoDeCaso, tarifas: Tarifas) -> Decimal:
    """Costo esperado de `casos` antes de gastar nada. Redondeado a centavos."""
    return (_costo(uso_por_caso, tarifas) * Decimal(casos)).quantize(_DOS)


def evaluar(
    casos: Iterable[CasoDeEvaluacion],
    *,
    fuente: str,
    extraer: Callable[[SourceDocument], ExtraccionConUso],
    clasificar: Callable[[ProductDnaDraft, date], Clasificacion],
    tarifas: Tarifas,
    fecha_minima: date | None = None,
    limite: int | None = None,
    errores_seguidos_para_abortar: int = 5,
) -> Reporte:
    """Corre los casos y arma el reporte. Un caso que falla no aborta la corrida.

    `limite` existe para el lote chico que va antes del conjunto completo: se
    cuentan como `casos` sólo los que se llegaron a mirar.

    SI EL DESTINO SE CAE, SE DEJA DE PAGAR

    Cada caso cuesta una llamada de extracción ANTES de clasificar. Cuando la
    base deja de responder, la extracción sigue funcionando —no la toca— y el
    harness seguiría comprando extracciones cuya clasificación no puede correr.
    El 23-sep eso costó unos $1.50 en 55 casos seguidos que no midieron nada.

    Cinco errores seguidos no son cinco casos raros: son un destino caído. Se
    corta, se dice en el reporte, y lo ya medido se conserva.
    """
    resultados: list[ResultadoDeCaso] = []
    excluidos: Counter[str] = Counter()
    seguidos = 0
    interrumpido: str | None = None
    simulacion = False
    de_modelo = False
    costo = Decimal(0)

    for i, caso in enumerate(casos):
        if limite is not None and i >= limite:
            break
        simulacion = simulacion or caso.data_origin == "SYNTHETIC"
        de_modelo = de_modelo or caso.verdad_de_modelo

        motivo = motivo_de_exclusion(caso, fecha_minima=fecha_minima)
        if motivo is not None:
            excluidos[motivo] += 1
            resultados.append(
                ResultadoDeCaso(
                    identificador=caso.identificador,
                    resultado="EXCLUIDO",
                    motivo=motivo,
                    hs6_esperado=caso.hs6_esperado,
                )
            )
            continue

        # SIN FUGAS: el documento se construye sólo con la descripción. Ni el
        # identificador del ruling viaja como `reference`.
        documento = SourceDocument(text=caso.descripcion, kind="text")
        try:
            extraccion = extraer(documento)
            clasificacion = clasificar(extraccion.dna, caso.fecha)
        except Exception as exc:
            motivo_error = f"{type(exc).__name__}: {exc}"[:300]
            resultados.append(
                ResultadoDeCaso(
                    identificador=caso.identificador,
                    resultado="ERROR",
                    motivo=motivo_error,
                    hs6_esperado=caso.hs6_esperado,
                )
            )
            seguidos += 1
            if seguidos >= errores_seguidos_para_abortar:
                interrumpido = (
                    f"{seguidos} errores seguidos; el último: {motivo_error}. "
                    "Se cortó para no seguir pagando extracciones que no se pueden medir."
                )
                break
            continue

        seguidos = 0

        uso = extraccion.uso.model_copy(update={"embedding": clasificacion.embedding_tokens})
        costo += _costo(uso, tarifas)
        obtenido = clasificacion.codigo[:6] if clasificacion.codigo else None
        resultados.append(
            ResultadoDeCaso(
                identificador=caso.identificador,
                resultado="EVALUADO",
                hs6_esperado=caso.hs6_esperado,
                hs6_obtenido=obtenido,
                acierto=obtenido == caso.hs6_esperado,
                estado_motor=clasificacion.estado,
                llego_a_rgi_3c=_RGI_3C in {_normalizar_regla(r) for r in clasificacion.rgi_path},
                degradado=not clasificacion.uso_vectores,
                uso=uso,
            )
        )

    evaluados = [r for r in resultados if r.resultado == "EVALUADO"]
    con_codigo = [r for r in evaluados if r.hs6_obtenido is not None]
    n = len(evaluados)
    aciertos = sum(1 for r in evaluados if r.acierto)

    return Reporte(
        fuente=fuente,
        casos=len(resultados),
        evaluados=n,
        excluidos=dict(excluidos),
        errores=sum(1 for r in resultados if r.resultado == "ERROR"),
        hs_accuracy=Acierto(aciertos=aciertos, comparados=n, porcentaje=_pct(aciertos, n)),
        acierto_cuando_responde=Acierto(
            aciertos=aciertos,
            comparados=len(con_codigo),
            porcentaje=_pct(aciertos, len(con_codigo)),
        ),
        tasa_insuficiente=_pct(
            sum(1 for r in evaluados if r.estado_motor == "INSUFFICIENT_INFORMATION"), n
        ),
        tasa_rgi_3c=_pct(sum(1 for r in evaluados if r.llego_a_rgi_3c), n),
        tasa_degradacion=_pct(sum(1 for r in evaluados if r.degradado), n),
        costo_usd=costo.quantize(_DOS),
        tarifas_fuente=tarifas.fuente,
        es_simulacion=simulacion,
        interrumpido=interrumpido,
        verdad_de_modelo=de_modelo,
        resultados=resultados,
    )
