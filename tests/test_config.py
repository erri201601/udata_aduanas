"""Tests de configuración: los puertos y secretos del dev server."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def test_puertos_por_defecto_evitan_los_ocupados() -> None:
    """8000 y 5432 están ocupados en el dev server; los defaults deben esquivarlos.

    Si alguien "corrige" estos valores a los estándar, la API chocará con otro
    proyecto y Postgres con la instancia nativa. El test documenta el porqué.
    """
    from apps.api.config import Settings

    settings = Settings(_env_file=None)  # type: ignore[call-arg]

    assert settings.api_port == 8080, "8000 lo ocupa otro proyecto en la laptop de P1"
    assert settings.postgres_port == 5433, "5432 lo ocupa el PostgreSQL nativo"


def test_sqlalchemy_url_se_arma_desde_las_partes() -> None:
    """Sin DATABASE_URL explícita, la URL se compone de host/puerto/usuario."""
    from apps.api.config import Settings

    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        postgres_host="db.example",
        postgres_port=5433,
        postgres_db="aduanero",
        postgres_user="aduanero_app",
        postgres_password="s3cr3t",  # valor de prueba, no un secreto real
    )

    assert settings.sqlalchemy_url == (
        "postgresql+psycopg://aduanero_app:s3cr3t@db.example:5433/aduanero"
    )


def test_database_url_explicita_tiene_prioridad() -> None:
    """DATABASE_URL gana sobre las partes: permite apuntar a otra instancia."""
    from apps.api.config import Settings

    explicita = "postgresql+psycopg://otro:pwd@10.0.0.1:5432/otra"
    settings = Settings(_env_file=None, database_url=explicita)  # type: ignore[call-arg]

    assert settings.sqlalchemy_url == explicita


def test_los_secretos_no_se_filtran_en_repr() -> None:
    """SecretStr evita que una contraseña acabe en un log o en un traceback (§40)."""
    from apps.api.config import Settings

    settings = Settings(_env_file=None, postgres_password="no-debe-aparecer")  # type: ignore[call-arg]

    assert "no-debe-aparecer" not in repr(settings)
    assert "no-debe-aparecer" not in str(settings)
    assert settings.postgres_password.get_secret_value() == "no-debe-aparecer"


def test_la_base_del_equipo_sale_del_entorno_no_del_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La contraseña de la base compartida no vive en `.env` ni en el código."""
    from apps.api.config import url_de_postgres

    monkeypatch.setenv("ADUANERO_SHARED_URL", "postgresql+psycopg://u:p@100.86.182.104:5433/a")

    assert url_de_postgres("shared").endswith("@100.86.182.104:5433/a")


def test_sin_la_variable_no_se_inventa_un_destino(monkeypatch: pytest.MonkeyPatch) -> None:
    """Callar aquí mediría la base equivocada creyendo medir la del equipo."""
    from apps.api.config import UrlCompartidaAusenteError, url_de_postgres

    monkeypatch.delenv("ADUANERO_SHARED_URL", raising=False)

    with pytest.raises(UrlCompartidaAusenteError, match="canal seguro"):
        url_de_postgres("shared")


def test_local_es_la_de_esta_maquina(monkeypatch: pytest.MonkeyPatch) -> None:
    """Y no se contamina con la compartida aunque esté definida."""
    from apps.api.config import get_settings, url_de_postgres

    monkeypatch.setenv("ADUANERO_SHARED_URL", "postgresql+psycopg://u:p@otra:5433/a")

    assert url_de_postgres("local") == get_settings().sqlalchemy_url
