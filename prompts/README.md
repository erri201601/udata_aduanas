# Prompts versionados

Convención de §30 del prompt maestro. Los carga `core.prompts.load_prompt`.

## Nombres

```text
prompts/<familia>/<nombre>.v<version>.md
```

`prompts/product_dna/extract.v0.1.md` da `prompt_id = "product_dna.extract"` y
`prompt_version = "0.1"`.

## Cabecera obligatoria

```text
---
prompt_id: product_dna.extract
prompt_version: 0.1
description: qué hace este prompt
---
cuerpo del prompt
```

`prompt_id` y `prompt_version` deben coincidir con la ruta y el nombre del
fichero; el cargador lo verifica y falla si divergen.

## Variables

Se sustituyen con `$nombre` (`string.Template`), no con llaves: los prompts
llevan ejemplos de JSON y las llaves chocarían.

```python
from core.prompts import load_prompt

prompt = load_prompt("product_dna.extract")        # última versión
prompt = load_prompt("product_dna.extract", "0.1") # versión fija
texto = prompt.render(documento=ficha_tecnica)
prompt.reference   # prompt_id, prompt_version, content_hash -> a la decisión
```

## Cambiar un prompt

Un prompt publicado no se edita: se crea la versión siguiente. Las decisiones
ya tomadas registran la versión con la que se produjeron y deben poder
reproducirse (§14 y §17 del maestro).
