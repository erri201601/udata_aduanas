-- ADUANERO OS — extensiones base.
-- Se ejecuta UNA sola vez, cuando el volumen pgdata está vacío.
-- Cualquier cambio de esquema posterior va por Alembic (§10.4 Persona 1).

CREATE EXTENSION IF NOT EXISTS vector;      -- pgvector: embeddings del RAG
CREATE EXTENSION IF NOT EXISTS pg_trgm;     -- búsqueda difusa de descripciones
CREATE EXTENSION IF NOT EXISTS unaccent;    -- texto normativo en español
CREATE EXTENSION IF NOT EXISTS btree_gin;   -- índices compuestos para vigencias
CREATE EXTENSION IF NOT EXISTS "uuid-ossp"; -- ids canónicos

-- Configuración de búsqueda en español para el corpus jurídico.
CREATE TEXT SEARCH CONFIGURATION es_unaccent (COPY = spanish);
ALTER TEXT SEARCH CONFIGURATION es_unaccent
    ALTER MAPPING FOR hword, hword_part, word
    WITH unaccent, spanish_stem;

-- Esquemas: separan el dato normativo real del operativo sintético (§9/§10 maestro).
CREATE SCHEMA IF NOT EXISTS regulatory;  -- OFFICIAL / PUBLIC / LICENSED
CREATE SCHEMA IF NOT EXISTS operational; -- SYNTHETIC hoy, real cuando llegue AJR
CREATE SCHEMA IF NOT EXISTS intelligence;-- decisiones, evidencia, hallazgos
CREATE SCHEMA IF NOT EXISTS raw;         -- landing de ingestión (§12: nunca saltarse RAW)
