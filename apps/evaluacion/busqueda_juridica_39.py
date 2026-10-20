"""Mide la búsqueda jurídica del §39 contra preguntas etiquetadas por personas.

    python -m apps.evaluacion.busqueda_juridica_39 --api http://127.0.0.1:8080
    python -m apps.evaluacion.busqueda_juridica_39 --api <api> --detalle

PREGUNTA A LA API, NO AL ROUTER

Lo que se mide es lo que recibe quien usa AduLex: `POST /copilot/consultas`,
con la recuperación, el grafo y la redacción del modelo tal como corren en el
servicio. Importar el router desde aquí sería que la evaluación dependiera de la
API, que es la dependencia que el §29 prohíbe, y además mediría otra cosa: un
proceso sin el `.env` ni la base del servicio.

SÓLO CUENTA LO QUE UNA PERSONA FIRMÓ

Las preguntas están en `preguntas_juridicas.json`. Qué artículo responde cada
una es una afirmación jurídica, y escribirla de memoria sería inventar
fundamento: sin `validado_por`, la pregunta no se manda ni se cuenta, y el
reporte dice cuántas esperan etiqueta. Con cero etiquetadas no hay métrica, y
el script lo dice en vez de imprimir 0 %.

NO ESCRIBE NADA. El Copilot sólo lee; sí llama al modelo, que cuesta tokens.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Final

import httpx
import structlog
from core.evaluation.busqueda_juridica import PreguntaEtiquetada, Reporte, evaluar

log = structlog.stdlib.get_logger("apps.evaluacion.busqueda_juridica_39")

PREGUNTAS: Final = Path(__file__).with_name("preguntas_juridicas.json")


def cargar(ruta: Path = PREGUNTAS) -> list[PreguntaEtiquetada]:
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    return [PreguntaEtiquetada.desde(p) for p in datos["preguntas"]]


def informe(reporte: Reporte, *, detalle: list[str]) -> str:
    n = len(reporte.preguntas)
    lineas = [
        "BÚSQUEDA JURÍDICA — §39 (contrato del Copilot, ADR 0010)",
        f"{n} pregunta(s) etiquetadas · {reporte.sin_etiquetar} esperan etiqueta",
        "",
    ]
    if n == 0:
        lineas.append(
            "Sin preguntas etiquetadas no hay métrica. Etiquétalas en "
            "apps/evaluacion/preguntas_juridicas.json (HUMAN_REVIEW_REQUIRED)."
        )
        return "\n".join(lineas)
    lineas += [m.linea() for m in reporte.medidas()]
    lineas.append("")
    lineas.append("unsupported answer rate: más bajo es mejor. Las otras dos, más alto.")
    lineas += detalle
    return "\n".join(lineas)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--api",
        required=True,
        help="Base de la API: http://127.0.0.1:8080 en el dev server.",
    )
    parser.add_argument("--limite", type=int, default=8, help="Pasajes por consulta.")
    parser.add_argument("--detalle", action="store_true")
    args = parser.parse_args(argv)

    todas = cargar()
    etiquetadas = [p for p in todas if p.etiquetada]
    resultados = []
    detalle: list[str] = []
    inicio = time.monotonic()

    with httpx.Client(base_url=args.api, timeout=120) as cliente:
        for pregunta in etiquetadas:
            try:
                r = cliente.post(
                    "/copilot/consultas",
                    json={
                        "pregunta": pregunta.pregunta,
                        "fecha": pregunta.fecha.isoformat(),
                        "limite": args.limite,
                    },
                )
                r.raise_for_status()
            except httpx.HTTPError as exc:
                # No se cuenta ni como acierto ni como fallo: se dice.
                print(f"!! {pregunta.id}: la API no respondió ({exc}); no se mide")
                continue
            respuesta: dict[str, Any] = r.json()
            resultado = evaluar(pregunta, respuesta)
            resultados.append(resultado)
            if args.detalle:
                detalle.append(
                    f"── {pregunta.id}: recuperó={resultado.recupero} "
                    f"citó {resultado.citadas_pertinentes}/{resultado.citadas} pertinentes · "
                    f"confidence {respuesta.get('confidence')} · "
                    f"{'SIN SUSTENTO' if resultado.sin_sustento else 'ok'}"
                )

    reporte = Reporte(preguntas=tuple(resultados), sin_etiquetar=len(todas) - len(etiquetadas))
    log.info(
        "evaluacion.busqueda_juridica_39",
        preguntas=len(resultados),
        sin_etiquetar=reporte.sin_etiquetar,
        duration_ms=int((time.monotonic() - inicio) * 1000),
        **{m.nombre.replace(" ", "_"): str(m.porcentaje) for m in reporte.medidas()},
    )
    print(informe(reporte, detalle=detalle))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
