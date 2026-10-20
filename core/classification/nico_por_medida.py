"""El NICO cuando la LIGIE lo distingue sólo por medidas (§19, ADR 0016).

Con varios NICO vigentes, `nico_de` se abstenía siempre. Medido el 20-oct
contra los veredictos de César: en cuatro de las fracciones del corpus
(7305.11.02, 7305.12.91, 7305.19.99, 7312.10.05) los NICO no distinguen por
materia ni por uso. Distinguen por **rangos de una medida** que la ficha trae
observada: espesor de pared, diámetro exterior, diámetro.

Esta regla resuelve sólo ese caso, y se abstiene ante cualquier otra cosa:

- **Todos** los NICO de la fracción, salvo «Los demás», tienen que ser
  condiciones numéricas que este módulo entiende por completo. Si uno solo
  dice algo más («De acero, …», «Cables plastificados», «Ollas de presión»),
  no se elige. Una regla que mira sólo los números no puede descartar el NICO
  que no habla de números.
- La ficha tiene que traer, observada o extraída del documento, **cada**
  medida que mencionan. Una medida inferida no basta, y una que falta tampoco:
  no se puede descartar un rango sin saber dónde cae el producto.
- Si caben varios, gana el **más específico**: aquel cuya región está
  contenida en la de todos los demás. La LIGIE solapa 7305.11.02 NICO 01
  («espesor inferior a 50.8 mm») con el NICO 02 («de 4.77 a 25.4 mm, diámetro
  exterior hasta 1,219.2 mm»). El 02 está dentro del 01, y es el que firmó
  César en las 16 partidas. Si ninguno está contenido en los demás, no se
  elige.
- «Los demás» sólo se elige si ningún otro cabe, y sólo con todo lo anterior
  cumplido.

Todo en `Decimal`: un rango «inferior a 25.4» no se compara en coma flotante.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

#: Qué atributo de la ficha mide cada magnitud que nombra la LIGIE. Sin alias:
#: el «diámetro» de un cable no es el «diámetro exterior» de un tubo, y
#: confundirlos sería elegir con una medida que el texto no menciona.
MAGNITUDES: Mapping[str, str] = {
    "espesor de pared": "espesor_pared_mm",
    "diametro exterior": "diametro_exterior_mm",
    "diametro": "diametro_mm",
}

_NUM = r"(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
_COTA = re.compile(
    r"(superior o igual a|superior a|inferior o igual a|inferior a)\s+" + _NUM + r"\s*mm\b\.?"
)
_MAGNITUD = re.compile("|".join(sorted(MAGNITUDES, key=len, reverse=True)))
#: Lo único que puede quedar de un NICO una vez quitadas sus cotas. Cualquier
#: otra palabra es una condición que esta regla no evalúa.
_CONECTORES = frozenset({"con", "de", "pero", "y"})
_RESIDUAL = "los demas"


@dataclass(frozen=True)
class Intervalo:
    """Un rango sobre una medida. `None` = sin límite por ese lado."""

    desde: Decimal | None = None
    desde_incluido: bool = True
    hasta: Decimal | None = None
    hasta_incluido: bool = True

    def contiene(self, x: Decimal) -> bool:
        if self.desde is not None and (
            x < self.desde or (x == self.desde and not self.desde_incluido)
        ):
            return False
        return not (
            self.hasta is not None
            and (x > self.hasta or (x == self.hasta and not self.hasta_incluido))
        )

    def dentro_de(self, otro: Intervalo) -> bool:
        """¿Todo este rango cae dentro de `otro`?"""
        if otro.desde is not None:
            if self.desde is None or self.desde < otro.desde:
                return False
            if self.desde == otro.desde and self.desde_incluido and not otro.desde_incluido:
                return False
        if otro.hasta is not None:
            if self.hasta is None or self.hasta > otro.hasta:
                return False
            if self.hasta == otro.hasta and self.hasta_incluido and not otro.hasta_incluido:
                return False
        return True


Condiciones = Mapping[str, Intervalo]
"""Atributo de la ficha → rango que exige el NICO."""


def _normalizar(texto: str) -> str:
    sin_acentos = "".join(
        c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn"
    )
    sin_parentesis = re.sub(r"\([^)]*\)", " ", sin_acentos)
    return re.sub(r"\s+", " ", sin_parentesis).strip()


def _numero(texto: str) -> Decimal:
    return Decimal(texto.replace(",", ""))


def _solo_conectores(texto: str) -> bool:
    palabras = re.findall(r"[a-z]+", texto)
    return all(p in _CONECTORES for p in palabras)


def leer_condiciones(descripcion: str) -> Condiciones | None:
    """Las condiciones numéricas de un NICO, o `None` si dice algo más.

    `None` no es «no hay condiciones»: es «hay algo que no sé evaluar». Un NICO
    sin ninguna cota tampoco se acepta, porque entonces no distingue nada que
    esta regla pueda ver.
    """
    texto = _normalizar(descripcion)
    marcas = list(_MAGNITUD.finditer(texto))
    if not marcas or not _solo_conectores(texto[: marcas[0].start()]):
        return None
    condiciones: dict[str, Intervalo] = {}
    for i, marca in enumerate(marcas):
        fin = marcas[i + 1].start() if i + 1 < len(marcas) else len(texto)
        tramo = texto[marca.end() : fin]
        atributo = MAGNITUDES[marca.group(0)]
        if atributo in condiciones:
            return None
        rango = Intervalo()
        cotas = list(_COTA.finditer(tramo))
        if not cotas:
            return None
        for cota in cotas:
            tipo, valor = cota.group(1), _numero(cota.group(2))
            if tipo.startswith("superior"):
                if rango.desde is not None:
                    return None
                rango = Intervalo(
                    valor, tipo == "superior o igual a", rango.hasta, rango.hasta_incluido
                )
            else:
                if rango.hasta is not None:
                    return None
                rango = Intervalo(
                    rango.desde, rango.desde_incluido, valor, tipo == "inferior o igual a"
                )
        if not _solo_conectores(_COTA.sub(" ", tramo)):
            return None
        condiciones[atributo] = rango
    return condiciones


def _dentro(a: Condiciones, b: Condiciones) -> bool:
    """¿La región de `a` está contenida en la de `b`? Una medida que `b` no
    menciona no lo limita."""
    return all(attr in a and a[attr].dentro_de(rango) for attr, rango in b.items())


def nico_por_medida(
    nicos: Sequence[tuple[str, str]], medidas: Mapping[str, Decimal]
) -> tuple[str | None, str]:
    """El NICO que eligen las medidas de la ficha, y por qué.

    `nicos` son `(código, descripción)` vigentes; `medidas`, las de la ficha
    que se observaron o extrajeron, ya en `Decimal`.
    """
    residual: str | None = None
    leidos: dict[str, Condiciones] = {}
    for codigo, descripcion in nicos:
        if _normalizar(descripcion).rstrip(".") == _RESIDUAL:
            residual = codigo
            continue
        condiciones = leer_condiciones(descripcion)
        if condiciones is None:
            return None, (
                f"el NICO {codigo} («{descripcion.strip()}») no distingue sólo por medidas"
            )
        leidos[codigo] = condiciones
    if not leidos:
        return None, "ningún NICO de la fracción distingue por medidas"

    necesarias = sorted({attr for c in leidos.values() for attr in c})
    faltan = [attr for attr in necesarias if attr not in medidas]
    if faltan:
        return None, f"la ficha no trae, observado, {', '.join(faltan)}"

    caben = [cod for cod, c in leidos.items() if all(r.contiene(medidas[a]) for a, r in c.items())]
    valores = ", ".join(f"{a}={medidas[a]}" for a in necesarias)
    if not caben:
        if residual is None:
            return None, f"con {valores} no cabe en ningún NICO y no hay «Los demás»"
        return residual, f"con {valores} no cabe en ningún otro NICO: «Los demás»"
    if len(caben) == 1:
        return caben[0], f"con {valores} sólo cabe en el NICO {caben[0]}"
    especificos = [a for a in caben if all(_dentro(leidos[a], leidos[b]) for b in caben if b != a)]
    if len(especificos) == 1:
        otros = ", ".join(c for c in caben if c != especificos[0])
        return especificos[0], (
            f"con {valores} caben {', '.join(caben)}; el {especificos[0]} es el más "
            f"específico (su rango está dentro del de {otros})"
        )
    return None, f"con {valores} caben {', '.join(caben)} y ninguno es más específico"


def medidas_de(atributos: Sequence[tuple[str, str | None]]) -> dict[str, Decimal]:
    """Las medidas legibles de `(nombre, valor)` ya filtrados a lo sólido.

    Un valor que no es un número no se adivina: se omite, y la regla dirá que
    falta.
    """
    salida: dict[str, Decimal] = {}
    for nombre, valor in atributos:
        if nombre not in MAGNITUDES.values() or not valor:
            continue
        try:
            salida[nombre] = _numero(valor.strip())
        except InvalidOperation:
            continue
    return salida
