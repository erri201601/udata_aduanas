"""Capa de repositorios: traduce el dominio a filas y viceversa.

Es la única capa que ve las dos orillas. `core/` produce objetos de dominio y
no importa persistencia (§29); `database/models/` define tablas y no sabe nada
de motores. Aquí se ensambla.

La dirección de las dependencias importa y es de un solo sentido:

    core/  ←── database/repositories/  ──→ database/models/

Si algún día un repositorio necesitara que `core/` supiera de sesiones, es
señal de que el diseño se rompió.
"""

from __future__ import annotations

from database.repositories.classification import save_classification

__all__ = ["save_classification"]
