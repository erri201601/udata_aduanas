"""El grafo en la búsqueda jurídica (§27): dice dónde mirar, no qué es verdad.

QUÉ PREGUNTA SE LE HACE AL GRAFO

Si la consulta nombra una fracción (`7312.10.05` o `73121005`), el grafo sabe
qué reglas citaron las decisiones que clasificaron mercancía en esa fracción:

    (TariffFraction {code})<-[:CLASSIFIED_AS]-(Decision)-[:CITES]->(LegalRule)

Eso no lo encuentra ni el texto completo ni el vector: la Ley Aduanera no
nombra fracciones, y una regla puede ser la que de verdad sostiene la
clasificación sin compartir una sola palabra con la pregunta.

LO QUE DEVUELVE SON IDS, NUNCA TEXTO

El grafo es una proyección de Postgres (`graph.proyeccion`) y no fundamenta
nada. Aquí sólo salen los ids de `legal_rules`; el texto, la vigencia y el
`content_hash` los lee `rag.recuperar` del almacén de chunks, con el mismo
filtro que cualquier otra búsqueda. Una regla que el grafo sugiere y no rige
ese día, no entra.

Y DICE LO VIEJO QUE ES

El grafo es una foto. `nota` lleva la fecha de la última proyección: una
sugerencia sacada de un grafo de septiembre no puede leerse como de hoy.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import TYPE_CHECKING, Any, Final

import structlog
from neo4j.exceptions import DriverError, Neo4jError

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from graph.preguntas import Consultable

log = structlog.stdlib.get_logger("graph.busqueda")

#: Una fracción de ocho dígitos, con o sin puntos: `7312.10.05`, `73121005`.
_FRACCION: Final = re.compile(r"\b(\d{4})\.?(\d{2})\.?(\d{2})\b")

_REGLAS: Final = """
MATCH (f:TariffFraction)
WHERE f.code IN $codigos
  AND f.valid_from <= date($fecha)
  AND (f.valid_to IS NULL OR f.valid_to >= date($fecha))
MATCH (f)<-[:CLASSIFIED_AS]-(d:Decision)-[:CITES]->(r:LegalRule)
RETURN r.id AS id, count(DISTINCT d) AS decisiones
ORDER BY decisiones DESC, id
LIMIT $limite
"""

_CUANDO: Final = "MATCH (p:Proyeccion {id: 'ultima'}) RETURN p.at AS at"


def fracciones_de(consulta: str) -> list[str]:
    """Las fracciones que nombra la consulta, en ocho dígitos y sin repetir."""
    return list(dict.fromkeys("".join(m) for m in _FRACCION.findall(consulta)))


class ExpansorDelGrafo:
    """`rag.ports.Expansor` respaldado por el grafo."""

    def __init__(self, grafo: Consultable) -> None:
        self._grafo = grafo
        self.nota: str | None = None

    def reglas_relacionadas(self, consulta: str, *, on_date: date, limit: int) -> Sequence[str]:
        codigos = fracciones_de(consulta)
        if not codigos:
            self.nota = "La pregunta no nombra ninguna fracción: el grafo no se consultó."
            return []
        try:
            filas = self._grafo.consultar(
                _REGLAS, codigos=codigos, fecha=on_date.isoformat(), limite=limit
            )
            cuando = self._grafo.consultar(_CUANDO)
        # Las dos familias del driver: `DriverError` (no hay conexión, el
        # servicio no responde) y `Neo4jError` (la base rechazó la consulta).
        except (DriverError, Neo4jError, OSError) as exc:
            # Degradar, no tumbar: la búsqueda por texto y vector sigue sirviendo.
            log.warning("graph.busqueda.no_disponible", error=type(exc).__name__)
            self.nota = f"El grafo no respondió ({type(exc).__name__}); se buscó sin él."
            return []

        proyectado = _fecha_de(cuando)
        ids = [str(f["id"]) for f in filas if f.get("id")]
        self.nota = (
            f"El grafo sugirió {len(ids)} regla(s) citadas por decisiones sobre "
            f"{', '.join(codigos)} (grafo proyectado {proyectado})."
        )
        log.info("graph.busqueda", fracciones=codigos, reglas=len(ids), proyectado=proyectado)
        return ids


def _fecha_de(filas: list[dict[str, Any]]) -> str:
    if not filas or not filas[0].get("at"):
        return "en una fecha que no consta"
    return f"el {str(filas[0]['at'])[:10]}"


@lru_cache(maxsize=1)
def _driver_compartido() -> Any:
    """Un driver por proceso, no uno por consulta: el driver es el pool."""
    from apps.api.config import get_settings
    from neo4j import GraphDatabase

    ajustes = get_settings()
    return GraphDatabase.driver(
        ajustes.neo4j_uri,
        auth=(ajustes.neo4j_user, ajustes.neo4j_password.get_secret_value()),
        connection_timeout=2.0,
        max_transaction_retry_time=2.0,
    )


def expansor_opcional() -> ExpansorDelGrafo | None:
    """El expansor si hay Neo4j configurado; `None` si no, sin fallar.

    Sin contraseña no se intenta conectar: no hay valor por omisión para una
    credencial. Con ella, el driver tiene tiempos cortos —el grafo es una
    ayuda, y una consulta no puede quedarse esperándolo— y se comparte.
    """
    from apps.api.config import get_settings

    if not get_settings().neo4j_password.get_secret_value():
        return None
    from graph.neo4j_grafo import Neo4jGrafo

    return ExpansorDelGrafo(Neo4jGrafo(_driver_compartido()))
