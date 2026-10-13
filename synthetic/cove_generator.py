"""`COVEGenerator` (§24 maestro).

Deliberadamente delgado, por la misma razón que
`ingestion/sintetico/load.py::_create_cove`: un COVE sintético no tiene
detrás un documento electrónico real, así que no hay `cove_type` que citar
contra un catálogo (ninguno verificable en el manual/FAQ de VUCEM) ni
`edocument_hash` que no sea una apariencia de verificabilidad inventada. Lo
único que este componente decide es el número de COVE, derivado del
`document_id` del pedimento -- igual que ya hace el cargador.
"""

from __future__ import annotations


def numero_cove(document_id: str) -> str:
    return f"COVE-{document_id}"
