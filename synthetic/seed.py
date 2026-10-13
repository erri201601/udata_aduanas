"""RNG determinista por seed (§10/§24 maestro).

Todo lo que genera `synthetic/` tiene que poder repetirse bit a bit dado el
mismo seed. `random.Random` ya es determinista por construcción; lo único
que hace falta es no compartir una sola instancia entre componentes, para
que agregar un generador nuevo no corra la secuencia de los demás.
"""

from __future__ import annotations

import random


def rng_for(seed: int, *salt: str) -> random.Random:
    """Un `Random` independiente por combinación `(seed, salt)`.

    `CompanyGenerator` y `ProductGenerator` corriendo con el mismo seed no
    se pisan el estado porque cada uno pide su propio `rng_for(seed,
    "company")` / `rng_for(seed, "product")` -- cambiar cuántos números le
    pide un componente nunca desincroniza a los demás.
    """
    clave = f"{seed}:{':'.join(salt)}"
    return random.Random(clave)
