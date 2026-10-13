"""Comprobación previa a la demo: cada cifra y cada traza del guion, contra el sistema vivo.

POR QUÉ EXISTE (7-oct)

El guion de la demo promete números concretos —98 de 98, TP 52, «En 9 de ellas
la única diferencia es el tipo de cambio»— y la base es COMPARTIDA: una
reclasificación, una carga o un veredicto nuevo los mueven sin avisar. Ese
mismo día cambiaron varias veces por arreglos legítimos. Presentar un número
que ya no es verdad delante de un cliente es peor que no presentarlo.

Esto se corre el día anterior y la mañana de la demo. Si algo se movió, lo
dice ANTES de entrar, con lo esperado y lo obtenido.

SÓLO LEE

No escribe nada: la clasificación de la laptop se hace en seco (sin
persistir) y las mediciones corren en una sesión que se revierte. Con
`--con-revision` sí lanza una auditoría del Espejo sobre el 600001 —lo mismo
que el botón «Revisar ahora» de la demo— para cronometrarla.

Uso:
    python -m apps.evaluacion.antes_de_la_demo
    python -m apps.evaluacion.antes_de_la_demo --con-revision

Si una cifra cambia A PROPÓSITO, se cambia aquí y en el guion a la vez.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import Session

#: Lo que dice el guion del 7-oct (`~/documentos_cliente_aduanero/DEMO_AJR.md`).
ESPERADO: dict[str, Any] = {
    "fracciones_vigentes": 8135,
    "nicos": 11503,
    "normas": {
        "Reglas Generales de Comercio Exterior para 2026": 537,
        "Ley Aduanera": 274,
        "Ley de los Impuestos Generales de Importación y de Exportación (Tarifa)": 94,
    },
    "correlaciones_nom": 456,
    "dias_fix": 192,
    "objetos_raw": 15,
    "laptop_estados": [
        "CONTINUE",
        "CONTINUE",
        "CONTINUE",
        "CONTINUE",
        "RESOLVED",
        "HUMAN_REVIEW_REQUIRED",
    ],
    "laptop_partidas_rgi1": 12,
    "laptop_subpartidas_rgi6": 9,
    "laptop_dictamen": "84713001",
    "dossier_sin_contestar": ["confidence", "money_impact"],
    "cable_001_004": ("RESOLVED", "73121005"),
    "cable_001_004_descartes": {
        "73121007": "CONTRADICCION",
        "73121008": "RESPUESTA_FIRMADA",
        "73121001": "RESPUESTA_FIRMADA",
    },
    "espejo_600001_cuota_en_lineas": [4, 8, 12],
    "espejo_600001_igi_iva_linea_2": ("2767.000000", "442.720000"),
    "espejo_600001_exposicion": "3295.730000",
    "espejo_600015_olla": "76151002",
    "espejo_600015_solo_documento": 9,
    "clasificacion": {
        "medibles": 157,
        "sin_fundamento": 11,
        "acerto": 98,
        "fallo": 0,
        "contra_dictamen": 43,
    },
    "deteccion": {"tp": 52, "fp": 0, "fn": 3, "tn": 126},
    "contra_el_motor": {"coinciden": 47, "discrepan": 0, "se_abstiene": 65},
    "bandeja": 0,
    "alcance_acero": (134, 181),
}

RAIZ = Path(__file__).resolve().parents[2]


@dataclass
class Resultado:
    nombre: str
    ok: bool
    esperado: str = ""
    obtenido: str = ""


def comparar(nombre: str, esperado: object, obtenido: object) -> Resultado:
    return Resultado(nombre, esperado == obtenido, str(esperado), str(obtenido))


# ── Entorno ─────────────────────────────────────────────────────────────────


def _direccion_de_la_api() -> str:
    """La API escucha en `TEAM_BIND_ADDR` del `.env`; sólo se lee esa clave."""
    entorno = RAIZ / ".env"
    if not entorno.exists():
        return "http://127.0.0.1:8080"
    for linea in entorno.read_text().splitlines():
        if linea.startswith("TEAM_BIND_ADDR="):
            return f"http://{linea.split('=', 1)[1].strip()}:8080"
    return "http://127.0.0.1:8080"


def _get(api: str, ruta: str) -> Any:
    with urllib.request.urlopen(f"{api}{ruta}", timeout=60) as r:
        return json.load(r)


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=RAIZ, capture_output=True, text=True, check=True
    ).stdout.strip()


def servicios(api: str, _s: Session) -> list[Resultado]:
    listo = _get(api, "/health/ready")
    caidos = [n for n, v in listo["services"].items() if v["status"] != "up"]
    with urllib.request.urlopen("http://127.0.0.1:5173/", timeout=10) as r:
        consola = r.status
    return [
        comparar("API lista", "ready", listo["status"]),
        comparar("servicios caídos", [], caidos),
        comparar("consola en 127.0.0.1:5173", 200, consola),
    ]


def rama(_api: str, _s: Session) -> list[Resultado]:
    """La máquina en `develop`, limpia y al día: «nadie cambia de rama el día de la demo»."""
    _git("fetch", "-q", "origin")
    return [
        comparar("rama del checkout", "develop", _git("branch", "--show-current")),
        comparar("cambios sin commit", "", _git("status", "--short")),
        comparar(
            "al día con origin/develop",
            _git("rev-parse", "origin/develop"),
            _git("rev-parse", "HEAD"),
        ),
    ]


# ── Sección 2: los datos ────────────────────────────────────────────────────


def datos(_api: str, s: Session) -> list[Resultado]:
    q = lambda sql: s.execute(sa.text(sql)).scalar()  # noqa: E731
    filas = s.execute(
        sa.text(
            """select d.title, count(r.id) from regulatory.legal_documents d
               join regulatory.legal_rules r on r.legal_document_id = d.id group by 1"""
        )
    ).all()
    normas: dict[str, int] = {str(f[0]): int(f[1]) for f in filas}
    from minio import Minio

    from apps.api.config import get_settings

    st = get_settings()
    cliente = Minio(
        st.minio_endpoint,
        access_key=st.minio_root_user,
        secret_key=st.minio_root_password.get_secret_value(),
        secure=st.minio_secure,
    )
    raw = len(list(cliente.list_objects(st.minio_bucket_raw, recursive=True)))
    return [
        comparar(
            "fracciones vigentes",
            ESPERADO["fracciones_vigentes"],
            q("select count(*) from regulatory.tariff_fractions where valid_to is null"),
        ),
        comparar("NICO", ESPERADO["nicos"], q("select count(*) from regulatory.nicos")),
        comparar("normas por documento", ESPERADO["normas"], normas),
        comparar(
            "correlaciones fracción → NOM",
            ESPERADO["correlaciones_nom"],
            q("select count(*) from regulatory.fraction_nom_requirements"),
        ),
        comparar(
            "días de FIX", ESPERADO["dias_fix"], q("select count(*) from regulatory.exchange_rates")
        ),
        comparar("objetos en RAW", ESPERADO["objetos_raw"], raw),
    ]


# ── Secciones 3 y 4: la clasificación en vivo ───────────────────────────────


def _producto(s: Session, sku: str) -> Any:
    return s.execute(
        sa.text("select id from operational.products where sku = :s"), {"s": sku}
    ).scalar_one()


def laptop(_api: str, s: Session) -> list[Resultado]:
    """La misma clasificación que el botón «Clasificar», en seco y con la fecha de hoy."""
    from database.repositories.preguntas import dictamen_de

    from apps.api.clasificacion import clasificar_borrador
    from apps.api.dna import cargar_borrador, version_vigente

    pid = _producto(s, "LAP-DEMO-001")
    borrador = cargar_borrador(s, pid)
    assert borrador is not None, "LAP-DEMO-001 sin ficha"
    inicio = time.perf_counter()
    traza = clasificar_borrador(
        s, borrador, operation_date=datetime.now(UTC).date(), trade_flow="IMPORT"
    ).outcome.trace
    segundos = time.perf_counter() - inicio
    pasos = {p.rule_id: p for p in traza.steps}
    ficha = version_vigente(s, pid)
    dictamen = dictamen_de(s, ficha.id) if ficha else None
    return [
        comparar(
            "laptop: estados de la traza",
            ESPERADO["laptop_estados"],
            [p.status.value for p in traza.steps],
        ),
        comparar(
            "laptop: partidas en la RGI 1",
            ESPERADO["laptop_partidas_rgi1"],
            len(pasos["RGI-1"].candidate_codes),
        ),
        comparar(
            "laptop: RGI 3 c) elige",
            ("8528", "0.4500"),
            (pasos["RGI-3c"].resolved_code, str(pasos["RGI-3c"].confidence)),
        ),
        comparar(
            "laptop: subpartidas en la RGI 6",
            ESPERADO["laptop_subpartidas_rgi6"],
            len(pasos["RGI-6"].candidate_codes),
        ),
        comparar(
            "laptop: dictamen del caso",
            ESPERADO["laptop_dictamen"],
            dictamen.fraction_code if dictamen else None,
        ),
        Resultado("laptop: tarda menos de 5 s", segundos < 5, "< 5 s", f"{segundos:.1f} s"),
    ]


def cable(_api: str, s: Session) -> list[Resultado]:
    fila = s.execute(
        sa.text(
            """select d.status, d.fraction_code, d.rgi_trace from intelligence.classification_decisions d
               join operational.products p on p.id = d.product_id
               where p.sku = 'PED_SIM_001-004' and d.data_origin <> 'HUMAN_VALIDATED'
               order by d.created_at desc limit 1"""
        )
    ).one()
    descartes = {
        x["code"]: x["por"] for paso in fila.rgi_trace for x in paso.get("descartadas") or []
    }
    return [
        comparar(
            "cable 001-004: resultado", ESPERADO["cable_001_004"], (fila.status, fila.fraction_code)
        ),
        comparar(
            "cable 001-004: descartes y de dónde salen",
            ESPERADO["cable_001_004_descartes"],
            descartes,
        ),
    ]


# ── Sección 5: el expediente ────────────────────────────────────────────────


def dossier(api: str, s: Session) -> list[Resultado]:
    vigente = s.execute(
        sa.text(
            """select d.id from intelligence.classification_decisions d
               join operational.products p on p.id = d.product_id
               where p.sku = 'LAP-DEMO-001' and d.data_origin <> 'HUMAN_VALIDATED'
               order by d.created_at desc limit 1"""
        )
    ).scalar_one()
    return [
        comparar(
            "dossier de la laptop: sin contestar",
            ESPERADO["dossier_sin_contestar"],
            sorted(_get(api, f"/evidence/{vigente}")["unanswered"]),
        )
    ]


# ── Sección 6: el Espejo ────────────────────────────────────────────────────


def _espejo(api: str, s: Session, numero: str) -> Any:
    pid = s.execute(
        sa.text("select id from operational.pedimentos where pedimento_number like :n"),
        {"n": f"%{numero}"},
    ).scalar_one()
    return _get(api, f"/pedimentos/{pid}/shadow")


def _tipos(linea: dict[str, Any]) -> set[str]:
    return {d["finding_type"] for d in linea["divergencias"]}


def espejo(api: str, s: Session) -> list[Resultado]:
    uno = _espejo(api, s, "600001")
    por_linea = {linea["line_number"]: linea for linea in uno["lineas"]}
    con_cuota = sorted(
        n for n, linea in por_linea.items() if "COMPENSATORY_DUTY_MISMATCH" in _tipos(linea)
    )
    linea_2 = {d["finding_type"]: d["impact_amount"] for d in por_linea[2]["divergencias"]}

    quince = _espejo(api, s, "600015")
    olla = next(linea for linea in quince["lineas"] if linea["line_number"] == 3)
    claves = [
        {
            (d["finding_type"], d["declared_value"], d["expected_value"])
            for d in linea["divergencias"]
            if not d["impact_amount"]
        }
        for linea in quince["lineas"]
    ]
    documento = set.intersection(*claves) if claves else set()
    solo_documento = sum(
        1
        for linea in quince["lineas"]
        if linea["divergencias"]
        and all(
            (d["finding_type"], d["declared_value"], d["expected_value"]) in documento
            for d in linea["divergencias"]
        )
    )
    return [
        comparar(
            "600001: líneas con cuota compensatoria",
            ESPERADO["espejo_600001_cuota_en_lineas"],
            con_cuota,
        ),
        comparar(
            "600001: IGI e IVA de la línea 2",
            ESPERADO["espejo_600001_igi_iva_linea_2"],
            (linea_2.get("IGI_RATE_MISMATCH"), linea_2.get("VAT_MISMATCH")),
        ),
        comparar(
            "600001: exposición cuantificada",
            ESPERADO["espejo_600001_exposicion"],
            uno["exposicion_cuantificada"],
        ),
        comparar(
            "600015: fracción esperada de la olla",
            ESPERADO["espejo_600015_olla"],
            olla["expected_fraction_code"],
        ),
        Resultado(
            "600015: la olla cita el dictamen",
            any(
                "Un clasificador dictaminó" in (d["rationale"] or "") for d in olla["divergencias"]
            ),
            "sí",
            "sí"
            if any(
                "Un clasificador dictaminó" in (d["rationale"] or "") for d in olla["divergencias"]
            )
            else "no",
        ),
        comparar(
            "600015: partidas que sólo difieren por el documento",
            ESPERADO["espejo_600015_solo_documento"],
            solo_documento,
        ),
    ]


def revision_en_vivo(api: str, s: Session) -> list[Resultado]:
    """Lo que hace el botón «Revisar ahora». Escribe una revisión: va detrás de `--con-revision`."""
    pid = s.execute(
        sa.text("select id from operational.pedimentos where pedimento_number like '%600001'")
    ).scalar_one()
    peticion = urllib.request.Request(
        f"{api}/pedimentos/{pid}/review",
        data=json.dumps({"iva_rate": "0.16", "dta_rate": "0.008"}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    inicio = time.perf_counter()
    with urllib.request.urlopen(peticion, timeout=180) as r:
        json.load(r)
    segundos = time.perf_counter() - inicio
    return [
        Resultado("«Revisar ahora» sobre el 600001", segundos < 30, "< 30 s", f"{segundos:.1f} s")
    ]


# ── Secciones 6 y 7: las mediciones ─────────────────────────────────────────


def mediciones(api: str, s: Session) -> list[Resultado]:
    from apps.evaluacion import clasificacion_39, deteccion_26

    c = clasificacion_39.medir(s)
    d = deteccion_26.medir(s).agregado
    contra = _get(api, "/metrics/classification")["contra_el_motor_de_hoy"]
    return [
        comparar(
            "clasificación",
            ESPERADO["clasificacion"],
            {
                "medibles": c.medibles,
                "sin_fundamento": c.sin_fundamento,
                "acerto": c.acerto,
                "fallo": c.fallo,
                "contra_dictamen": c.contra_dictamen,
            },
        ),
        comparar(
            "detección", ESPERADO["deteccion"], {"tp": d.tp, "fp": d.fp, "fn": d.fn, "tn": d.tn}
        ),
        comparar(
            "contra el motor de hoy",
            ESPERADO["contra_el_motor"],
            {k: contra[k] for k in ("coinciden", "discrepan", "se_abstiene")},
        ),
    ]


def bandeja_y_vocabulario(api: str, _s: Session) -> list[Resultado]:
    alcance = _get(api, "/review/vocabulario/alcance?termino_ficha=acero")
    return [
        comparar("bandeja", ESPERADO["bandeja"], len(_get(api, "/review?limit=200"))),
        comparar(
            "tablero: esperan a una persona",
            ESPERADO["bandeja"],
            _get(api, "/dashboard")["clasificaciones"]["requieren_revision"],
        ),
        comparar(
            "alcance de «acero»",
            ESPERADO["alcance_acero"],
            (alcance["fichas"], alcance["de_un_total"]),
        ),
    ]


COMPROBACIONES: list[tuple[str, Callable[[str, Session], list[Resultado]]]] = [
    ("Servicios", servicios),
    ("Rama", rama),
    ("§2 · Los datos", datos),
    ("§3 · La laptop en vivo", laptop),
    ("§4 · El cable que aprendió", cable),
    ("§5 · El expediente", dossier),
    ("§6 · El Espejo", espejo),
    ("§6-7 · Las mediciones", mediciones),
    ("Bandeja y vocabulario", bandeja_y_vocabulario),
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--con-revision", action="store_true", help="cronometrar «Revisar ahora» (escribe)"
    )
    args = parser.parse_args(argv)

    from apps.api.db import get_sessionmaker

    api = _direccion_de_la_api()
    comprobaciones = COMPROBACIONES + ([("En vivo", revision_en_vivo)] if args.con_revision else [])
    fallos = 0
    sesion = get_sessionmaker()()
    try:
        for titulo, comprobar in comprobaciones:
            print(f"\n{titulo}")
            try:
                resultados = comprobar(api, sesion)
            except Exception as error:  # una que falle no esconde las demás
                resultados = [
                    Resultado(
                        titulo,
                        False,
                        "que se pudiera comprobar",
                        f"{type(error).__name__}: {error}",
                    )
                ]
            for r in resultados:
                fallos += not r.ok
                marca = "✓" if r.ok else "✗"
                detalle = (
                    "" if r.ok else f"\n      esperado {r.esperado}\n      obtenido {r.obtenido}"
                )
                print(f"  {marca} {r.nombre}{detalle}")
    finally:
        sesion.rollback()
        sesion.close()

    print(
        "\nTODO COMO EN EL GUION."
        if fallos == 0
        else f"\n{fallos} COSA(S) NO COINCIDEN CON EL GUION: revísalas antes de entrar."
    )
    return 0 if fallos == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
