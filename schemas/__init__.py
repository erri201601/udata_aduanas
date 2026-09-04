"""Contratos Pydantic v2 compartidos del Canonical Data Model.

Espejo de `database/models/`: por cada entidad hay `*Create` (entrada),
`*Read` (salida, con `id` y timestamps) y `*Update` (parche, todo opcional).
La capa de dominio (`core/`) y la API (`apps/api/`) hablan estos tipos, nunca
los modelos SQLAlchemy directamente.
"""
