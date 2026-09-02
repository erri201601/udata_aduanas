# TAREA — Model Provider + Frontend base

**Asignada a:** Persona 3  
**Aprueba:** Persona 1  
**Entrega:** PR contra `develop`

Ninguna de estas tareas depende de que existan tablas. Puedes empezar hoy.

---

## 0. Antes de escribir una línea

Lee `docs/00_ADUANERO_OS_PROMPT_MAESTRO.md` completo, §29 y §32, y `CLAUDE.md`.
Después inspecciona el repositorio real: no asumas que existe nada.

---

## A. ModelProvider — rama `feature/model-provider`

**El objetivo real:** que el día que cambiemos de proveedor de IA, o que un
cliente exija que todo corra en local, no haya que tocar una sola línea de
`core/`.

### Interfaz

```python
class ModelProvider(Protocol):
    def generate(...) -> str: ...
    def generate_structured(...) -> BaseModel: ...   # salida validada por Pydantic
    def embed(...) -> list[float]: ...
    def analyze_image(...) -> str: ...               # fichas técnicas, fotos de producto
```

Adaptadores en `core/llm/providers/`: `OpenAIProvider`, `AnthropicProvider`,
`GeminiProvider`, y deja el hueco de `LocalProvider`.

### Reglas duras

1. **Ningún SDK de proveedor se importa dentro de `core/`** fuera de
   `core/llm/providers/`. El dominio nunca sabe qué modelo hay debajo (§29).
2. Las llaves salen de `apps/api/config.py`, que ya las lee de `.env`. Un
   proveedor sin llave queda deshabilitado, no revienta al importar.
3. `generate_structured()` valida contra un modelo Pydantic y **reintenta** si
   la salida no valida. Nunca devuelvas JSON sin validar.
4. Toda llamada registra `model_provider`, `model_name`, `prompt_version`,
   tokens y latencia — son campos del Canonical Model (§8), no adorno.
5. Errores explícitos: timeout, rate limit y filtro de contenido son
   excepciones propias, no un `None` silencioso.
6. **Tests con mocks. Cero llamadas reales** en la suite.

---

## B. Prompts versionados — misma rama

`prompts/product_dna/` con la convención de versionado (§30). Cada prompt
registra `prompt_id` y `prompt_version`. Sin lógica de negocio todavía:
estructura, carga y versionado.

---

## C. Frontend base — rama `feature/web-scaffold`

`apps/web/` con React + TypeScript + Vite.

Apunta a `http://100.86.182.104:8080` o `http://localhost:8080`. El CORS ya
está abierto para `localhost:5173`.

Empieza por lo que **ya tiene endpoint real**: `GET /health/ready` devuelve el
estado de los cuatro servicios. Una pantalla de estado del sistema es la
primera cosa que puedes construir contra datos de verdad.

Después el layout de las pantallas de §32, sin datos: Executive Dashboard,
Product DNA, Classification, Pedimento Shadow, Finding Detail, Regulatory
Sentinel, Copilot.

### Regla que no es decoración

Cuando pintes datos operativos, marca **`SYNTHETIC DEMO DATA`** de forma
visible (§33). Las fuentes jurídicas pueden marcarse `OFFICIAL SOURCE`. Que
alguien confunda un pedimento simulado con uno real en una demo ante AJR es el
peor fallo posible de este producto.

Genera el cliente TypeScript desde `http://100.86.182.104:8080/openapi.json`
en vez de escribir los tipos a mano.

---

## Definition of Done

`pytest` verde · `ruff check .` limpio · `mypy` limpio · sin secretos ·
type hints completos · PR contra `develop`.

Si necesitas cambiar un contrato central, detente y marca
`ARCHITECTURE_DECISION_REQUIRED`.

## Al terminar, reporta con el formato de §46 del maestro.
