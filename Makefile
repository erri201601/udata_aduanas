# ADUANERO OS — atajos de desarrollo
.DEFAULT_GOAL := help
SHELL := /bin/bash
VENV  := .venv/bin

.PHONY: help venv install up down logs ps api test lint fmt migrate revision reset-db health smoke service-status service-restart service-logs backup backup-list backup-timer merge antes-de-la-demo

help: ## Muestra esta ayuda
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

venv: ## Crea el entorno virtual
	python3 -m venv .venv

install: venv ## Instala dependencias de desarrollo
	$(VENV)/pip install --upgrade pip
	$(VENV)/pip install -e ".[dev]"

up: ## Levanta la infraestructura (requiere Docker)
	docker compose up -d
	docker compose ps

down: ## Detiene la infraestructura (conserva los datos)
	docker compose down

logs: ## Sigue los logs de los contenedores
	docker compose logs -f

ps: ## Estado de los contenedores
	docker compose ps

api: ## Arranca la API en primer plano (desarrollo)
	$(VENV)/uvicorn apps.api.main:app --reload --port 8080

service-status: ## Estado del servicio systemd de la API
	systemctl --user status aduanero-api --no-pager

service-restart: ## Reinicia la API tras cambiar código
	systemctl --user restart aduanero-api && systemctl --user is-active aduanero-api

service-logs: ## Logs en vivo de la API
	journalctl --user -u aduanero-api -f


test: ## Ejecuta los tests
	$(VENV)/pytest

merge: ## Mergea un PR sólo si los seis jobs del CI pasaron (make merge PR=47)
	@test -n "$(PR)" || { echo "uso: make merge PR=<número>"; exit 2; }
	@./infrastructure/scripts/merge_pr.sh $(PR)

lint: ## ruff + mypy
	$(VENV)/ruff check .
	$(VENV)/ruff format --check .
	@# El MISMO alcance que el CI. Con menos, `make lint` daba verde sobre
	@# un error que el CI sí veía: 130 archivos aquí contra 177 allí.
	$(VENV)/mypy apps core database schemas ingestion rag graph

fmt: ## Formatea y autocorrige
	$(VENV)/ruff format .
	$(VENV)/ruff check --fix .

migrate: ## Aplica las migraciones pendientes
	$(VENV)/alembic upgrade head

revision: ## Genera una migración: make revision M="descripcion"
	$(VENV)/alembic revision --autogenerate -m "$(M)"

smoke: ## Verifica el stack completo (extensiones, buckets, auth, exposición)
	./infrastructure/scripts/smoke_test.sh

antes-de-la-demo: ## Comprueba cada cifra del guion de la demo contra el sistema vivo (sólo lee)
	$(VENV)/python -m apps.evaluacion.antes_de_la_demo

health: ## Consulta los health checks
	@curl -s http://localhost:8080/health | python3 -m json.tool
	@curl -s http://localhost:8080/health/ready | python3 -m json.tool

backup: ## Respalda PostgreSQL y MinIO, y verifica la restauración
	./infrastructure/scripts/backup.sh --verify

backup-list: ## Lista los respaldos disponibles
	./infrastructure/scripts/restore.sh

backup-timer: ## Estado del respaldo automático diario
	systemctl --user list-timers aduanero-backup --no-pager
	journalctl --user -u aduanero-backup -n 20 --no-pager

reset-db: ## ⚠️ BORRA todos los volúmenes y vuelve a levantar
	@read -p "Esto borra TODOS los datos. Escribe 'si' para continuar: " ok; \
	  [ "$$ok" = "si" ] && docker compose down -v && docker compose up -d || echo "cancelado"
