"""Mide el Product DNA del §39 contra fichas con respuesta conocida.

    python -m apps.evaluacion.product_dna_39
    python -m apps.evaluacion.product_dna_39 --proveedor anthropic --detalle

Pasa cada ficha de `fichas_de_referencia.py` por el camino de producción —el
`LlmExtractor` con su prompt versionado y el saneamiento de
`core.product_dna.engine`— y compara con la respuesta conocida. Las cuatro
medidas salen con su n y su margen de Wilson al 95 %.

NO TOCA LA BASE. Las fichas viven en el código y el resultado se imprime: una
evaluación que escribe deja de medir lo que dice medir. SÍ llama al modelo, así
que cuesta tokens y necesita la llave del proveedor en el entorno.

Mide el motor como está, con el prompt que usa producción
(`core.product_dna.llm_extractor.PROMPT_VERSION`), y lo imprime: un número sin
la versión del prompt que lo produjo no se puede comparar con el siguiente.
"""

from __future__ import annotations

import argparse
import time
from typing import TYPE_CHECKING, cast

import structlog
from core.evaluation.product_dna import Reporte, comparar
from core.llm.errors import ModelProviderError
from core.llm.registry import build_provider, get_default_provider
from core.product_dna.engine import extract
from core.product_dna.llm_extractor import PROMPT_ID, PROMPT_VERSION, LlmExtractor
from core.product_dna.types import SourceDocument

from apps.evaluacion.fichas_de_referencia import FICHAS

if TYPE_CHECKING:
    from core.llm.base import ModelProvider

log = structlog.stdlib.get_logger("apps.evaluacion.product_dna_39")


def informe(reporte: Reporte, *, modelo: str, detalle: bool) -> str:
    lineas = [
        "PRODUCT DNA — §39 (SYNTHETIC DEMO DATA: fichas de referencia)",
        f"prompt {PROMPT_ID} v{PROMPT_VERSION} · modelo {modelo} · {len(reporte.fichas)} fichas",
        "",
    ]
    lineas += [m.linea() for m in reporte.medidas()]
    inferidas = sum(f.alucinados_como_inferencia for f in reporte.fichas)
    lineas.append(
        f"  de las alucinaciones, {inferidas} venían declaradas como INFERRED "
        "(no se presentaron como hechos)"
    )
    lineas.append("")
    lineas.append("hallucinated attribute rate: más bajo es mejor. Las otras tres, más alto.")
    if detalle:
        for f in reporte.fichas:
            if f.fallos:
                lineas.append(f"\n── {f.id}")
                lineas += [f"   {fallo}" for fallo in f.fallos]
    return "\n".join(lineas)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--proveedor", help="anthropic, openai, gemini… Por omisión, el del .env.")
    parser.add_argument("--detalle", action="store_true", help="Enseña qué falló en cada ficha.")
    args = parser.parse_args(argv)

    try:
        proveedor = (
            build_provider(name=args.proveedor) if args.proveedor else get_default_provider()
        )
    except ModelProviderError as exc:
        print(f"No hay proveedor de modelo con el que medir: {exc}")
        return 2
    extractor = LlmExtractor(cast("ModelProvider", proveedor))

    resultados = []
    inicio = time.monotonic()
    for ficha in FICHAS:
        try:
            borrador = extract(
                SourceDocument(text=ficha.texto, kind="text", reference=ficha.id),
                extractor=extractor,
            )
        except ModelProviderError as exc:
            # Una ficha que no se pudo leer no se cuenta como acierto ni como
            # fallo: se dice, y la medida se queda con menos n.
            print(f"!! {ficha.id}: el proveedor falló ({type(exc).__name__}); no se mide")
            continue
        resultados.append(comparar(ficha, borrador))

    reporte = Reporte(fichas=tuple(resultados))
    modelo = extractor.last_metadata.model_name if extractor.last_metadata else "desconocido"
    log.info(
        "evaluacion.product_dna_39",
        fichas=len(resultados),
        prompt_version=PROMPT_VERSION,
        model=modelo,
        duration_ms=int((time.monotonic() - inicio) * 1000),
        **{m.nombre.replace(" ", "_"): str(m.porcentaje) for m in reporte.medidas()},
    )
    print(informe(reporte, modelo=modelo, detalle=args.detalle))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
