"""Modelos SQLAlchemy del Canonical Data Model.

Alembic importa este paquete para descubrir metadata. Cada modelo nuevo debe
importarse aquí, o su tabla no aparecerá en las migraciones autogeneradas.
"""

from database.models.base import Base

__all__ = ["Base"]
