"""El catálogo de 12 productos y 3 proveedores del corpus espejo V1.

NO SON PRODUCTOS NUEVOS -- son los mismos `P001`..`P012` y los mismos 3
proveedores de `sintetico/corpus_espejo_v1_20260921.json` (el corpus ya
cargado, 15 pedimentos, 181 partidas, 133 veredictos de César). Se
transcriben aquí verbatim (verificado contra el JSON real en MinIO,
13-oct-2026) para que cualquier pedimento NUEVO que este paquete genere
declare la MISMA mercancía que ya existe -- es la condición que puso
Persona 1 para no perder los veredictos: nada de productos nuevos.

Lo que sí cambia entre una carga y otra es el PEDIMENTO (número, fecha,
importador, partidas, anomalías): eso es operación nueva sobre la misma
mercancía, exactamente como pasaría si la misma empresa importa el mismo
producto dos veces.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProductFicha:
    id: str
    name: str
    description: str
    spec: dict[str, object]
    #: Fracción/NICO con los que este producto se declaró en el corpus
    #: real, verbatim (no inventados) -- el valor "correcto" de referencia
    #: para que un escenario nuevo pueda declarar lo mismo o, a propósito,
    #: algo distinto.
    fraction_code: str
    nico_code: str


#: Las 12 fichas reales, en el mismo orden que el JSON.
PRODUCT_CATALOG: dict[str, ProductFicha] = {
    "P001": ProductFicha(
        id="P001",
        name="Olla de presión de aluminio, 6 L",
        description=(
            "OLLA DE PRESION DE ALUMINIO PARA USO DOMESTICO, CAPACIDAD 6 L, CUERPO DE "
            "ALUMINIO, TAPA CON VALVULA DE SEGURIDAD, SIN RECUBRIMIENTO ANTIADHERENTE"
        ),
        spec={
            "material": "aluminio",
            "uso": "domestico/cocina",
            "tipo": "olla de presion",
            "capacidad_l": 6,
            "mecanismo": "tapa con valvula de seguridad",
            "recubrimiento": "sin antiadherente",
        },
        fraction_code="76151002",
        nico_code="01",
    ),
    "P002": ProductFicha(
        id="P002",
        name="Fregadero de acero inoxidable",
        description=(
            "FREGADERO DE ACERO INOXIDABLE AISI 304, UNA TINA, 600 X 500 X 220 MM, "
            "ESPESOR 0.8 MM, PARA INSTALACION EN COCINA"
        ),
        spec={
            "material": "acero inoxidable AISI 304",
            "tipo": "fregadero una tina",
            "dimensiones_mm": "600x500x220",
            "espesor_mm": 0.8,
            "uso": "cocina",
        },
        fraction_code="73241001",
        nico_code="00",
    ),
    "P003": ProductFicha(
        id="P003",
        name="Vajilla de porcelana",
        description=(
            "JUEGO DE VAJILLA DE PORCELANA PARA SERVICIO DE MESA, 24 PIEZAS, PLATOS "
            "TAZAS Y TAZONES, USO DOMESTICO"
        ),
        spec={
            "material": "porcelana",
            "uso": "servicio de mesa",
            "presentacion": "juego 24 piezas",
            "contenido": ["platos", "tazas", "tazones"],
        },
        fraction_code="69111001",
        nico_code="00",
    ),
    "P004": ProductFicha(
        id="P004",
        name="Vajilla cerámica no porcelana",
        description=(
            "VAJILLA DE CERAMICA VIDRIADA, NO PORCELANA, PARA SERVICIO DE MESA, JUEGO "
            "DE 16 PIEZAS, USO DOMESTICO"
        ),
        spec={
            "material": "ceramica vidriada",
            "porcelana": False,
            "uso": "servicio de mesa",
            "presentacion": "juego 16 piezas",
        },
        fraction_code="69120099",
        nico_code="01",
    ),
    "P005": ProductFicha(
        id="P005",
        name="Cable de acero <12.7 mm",
        description=(
            "CABLE DE ACERO GALVANIZADO, CONSTRUCCION 6X19, DIAMETRO 10 MM, ALMA DE "
            "FIBRA, EN ROLLOS, PARA IZADO INDUSTRIAL"
        ),
        spec={
            "material": "acero galvanizado",
            "diametro_mm": 10,
            "construccion": "6x19",
            "alma": "fibra",
            "uso": "izado industrial",
        },
        fraction_code="73121099",
        nico_code="05",
    ),
    "P006": ProductFicha(
        id="P006",
        name="Cable de acero 12.7-25.4 mm",
        description=(
            "CABLE DE ACERO SIN RECUBRIMIENTO, CONSTRUCCION 6X36, DIAMETRO 18 MM, ALMA "
            "DE ACERO, LUBRICADO, PARA GRUA"
        ),
        spec={
            "material": "acero",
            "diametro_mm": 18,
            "construccion": "6x36",
            "alma": "acero",
            "lubricado": True,
            "uso": "grua",
        },
        # EL DICTAMEN, NO LA DECLARACIÓN DEL CORPUS (20-oct)
        #
        # El corpus original declaraba 73121099 para este cable, y César lo
        # dictaminó 73121005 NICO 02 en 15 partidas (un 6x36 no cumple «7
        # alambres»). Tomar la declaración como «correcta» hacía que cada
        # pedimento limpio generado con este cable saliera con un hallazgo
        # cierto contado como falso positivo.
        fraction_code="73121005",
        nico_code="02",
    ),
    "P007": ProductFicha(
        id="P007",
        name="Cable de acero >=25.4 mm",
        description=(
            "CABLE DE ACERO, CONSTRUCCION 8X36, DIAMETRO 32 MM, ALMA DE ACERO "
            "INDEPENDIENTE, PARA EQUIPO DE ELEVACION"
        ),
        spec={
            "material": "acero",
            "diametro_mm": 32,
            "construccion": "8x36",
            "alma": "acero independiente",
            "uso": "elevacion",
        },
        fraction_code="73121099",
        nico_code="07",
    ),
    "P008": ProductFicha(
        id="P008",
        name="Tubería SAW gran diámetro",
        description=(
            "TUBERIA DE ACERO AL CARBONO PARA OLEODUCTO, SOLDADA LONGITUDINALMENTE POR "
            "ARCO SUMERGIDO SAW, DIAMETRO EXTERIOR 914.4 MM, ESPESOR 12.7 MM, API 5L X65"
        ),
        spec={
            "material": "acero al carbono",
            "proceso_soldadura": "SAW longitudinal",
            "diametro_exterior_mm": 914.4,
            "espesor_pared_mm": 12.7,
            "norma": "API 5L X65",
            "uso": "oleoducto",
        },
        fraction_code="73051102",
        nico_code="02",
    ),
    "P009": ProductFicha(
        id="P009",
        name="Tubería longitudinal gran diámetro",
        description=(
            "TUBERIA DE ACERO AL CARBONO SOLDADA LONGITUDINALMENTE HFW, DIAMETRO "
            "EXTERIOR 508 MM, ESPESOR DE PARED 20 MM, PARA CONDUCCION DE FLUIDOS"
        ),
        spec={
            "material": "acero al carbono",
            "proceso_soldadura": "HFW longitudinal",
            "diametro_exterior_mm": 508,
            "espesor_pared_mm": 20,
            "uso": "conduccion de fluidos",
        },
        fraction_code="73051291",
        nico_code="01",
    ),
    "P010": ProductFicha(
        id="P010",
        name="Tubería helicoidal gran diámetro",
        description=(
            "TUBERIA DE ACERO AL CARBONO CON COSTURA HELICOIDAL SAW, DIAMETRO EXTERIOR "
            "1219 MM, ESPESOR DE PARED 16 MM, PARA CONDUCCION DE AGUA INDUSTRIAL"
        ),
        spec={
            "material": "acero al carbono",
            "proceso_soldadura": "SAW helicoidal",
            "diametro_exterior_mm": 1219,
            "espesor_pared_mm": 16,
            "uso": "conduccion agua industrial",
        },
        fraction_code="73051999",
        nico_code="01",
    ),
    "P011": ProductFicha(
        id="P011",
        name="Utensilio doméstico de acero inoxidable",
        description=(
            "SARTEN DE ACERO INOXIDABLE PARA COCINA, DIAMETRO 28 CM, MANGO DE ACERO, "
            "SIN RECUBRIMIENTO ANTIADHERENTE"
        ),
        spec={
            "material": "acero inoxidable",
            "tipo": "sarten",
            "diametro_cm": 28,
            "recubrimiento": "sin antiadherente",
            "uso": "cocina",
        },
        fraction_code="73239305",
        nico_code="00",
    ),
    "P012": ProductFicha(
        id="P012",
        name="Esponja/estropajo de acero",
        description=(
            "ESTROPAJO DE ACERO INOXIDABLE PARA LIMPIEZA DOMESTICA, PRESENTACION EN "
            "CAJAS DE 12 UNIDADES"
        ),
        spec={
            "material": "acero inoxidable",
            "tipo": "estropajo",
            "uso": "limpieza domestica",
            "presentacion": "caja 12 unidades",
        },
        fraction_code="73231001",
        nico_code="00",
    ),
    # P013 (20-oct): la primera ficha que no viene del corpus original. Hacía
    # falta una mercancía cuya fracción exija una NOM SIN acotación para
    # sembrar MISSING_NOM: ninguna de las 12 la tiene. 7321.11.01 exige la
    # NOM-025-ENER-2013 (Anexo 2.4.1) y tiene un solo NICO. Producto nuevo:
    # no toca ninguna ficha con veredicto de César.
    "P013": ProductFicha(
        id="P013",
        name="Estufa de gas doméstica",
        description=(
            "ESTUFA DE GAS PARA USO DOMESTICO, 4 QUEMADORES Y HORNO, CUERPO DE ACERO "
            "ESMALTADO, PARA GAS L.P. Y NATURAL"
        ),
        spec={
            "material": "acero esmaltado",
            "funcion": "cocinar",
            "combustible": "gas L.P. y natural",
            "quemadores": 4,
            "uso": "domestico",
        },
        fraction_code="73211101",
        nico_code="00",
    ),
}

#: Las fracciones de la cuota compensatoria del cable de acero de China
#: (ADR 0009) -- P005/P006/P007 caen aquí según su diámetro.
FRACCIONES_CUOTA_CABLE_ACERO = frozenset({"73121001", "73121005", "73121007", "73121099"})


@dataclass(frozen=True)
class SupplierFicha:
    name: str
    country: str
    incoterm: str
    currency: str
    address: str


#: Los 3 proveedores reales del corpus -- mismo criterio que
#: `PRODUCT_CATALOG`: no se inventan proveedores nuevos.
SUPPLIERS: tuple[SupplierFicha, ...] = (
    SupplierFicha(
        name="ORIENTAL TECHNICAL SUPPLY CO. LTD.",
        country="CHN",
        incoterm="CIF",
        currency="USD",
        address="88 EAST INDUSTRIAL ROAD, SHENZHEN, CHINA",
    ),
    SupplierFicha(
        name="BHARAT MERCANTILE EXPORTS PVT LTD",
        country="IND",
        incoterm="DAP",
        currency="USD",
        address="42 INDUSTRIAL ESTATE, PUNE, INDIA",
    ),
    SupplierFicha(
        name="ANATOLIA INDUSTRIAL GOODS AS",
        country="TUR",
        incoterm="FOB",
        currency="USD",
        address="16 SANAYI CAD., BURSA, TURQUIA",
    ),
)

#: Mismos valores que los 15 pedimentos ya cargados -- una aduana, un
#: régimen, una clave de documento. El generador puede variar `pedimento_key`
#: a propósito para el escenario `WRONG_IDENTIFIER` (necesita una clave
#: distinta de `A1`, la única para la que no hay ningún identificador
#: estructurable exigido -- ver ADR 0012).
ENTRY_CUSTOMS = "470"
REGIME = "IMD"
PEDIMENTO_KEY = "A1"
