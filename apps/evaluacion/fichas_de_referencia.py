"""Fichas técnicas con respuesta conocida, para medir el Product DNA (§39).

SYNTHETIC DEMO DATA. Son fichas escritas para esta medida: ningún fabricante,
marca ni modelo es real. La respuesta es conocida POR CONSTRUCCIÓN: cada valor
de `esperado` está escrito literalmente en el texto, y cada nombre de
`ausentes` no aparece ni se puede deducir de él.

No afirman nada jurídico ni arancelario: describen mercancías. Por eso se
pueden escribir sin fuente, a diferencia de las preguntas de la búsqueda
jurídica, cuyas respuestas tienen que etiquetarlas personas.

Seis fichas son pocas, y el margen de Wilson lo dirá en cada medida. Añadir
fichas es añadir entradas aquí: el script no cambia.
"""

from __future__ import annotations

from typing import Final

from core.evaluation.product_dna import FichaDeReferencia

FICHAS: Final[tuple[FichaDeReferencia, ...]] = (
    FichaDeReferencia(
        id="cable-acero-6x36",
        texto=(
            "FICHA TÉCNICA — CABLE DE ACERO GALVANIZADO\n"
            "Fabricante: Aceros Demo del Norte, S.A.\n"
            "Modelo: CAG-636-10\n"
            "Material: acero galvanizado\n"
            "Construcción: 6x36 con alma de acero\n"
            "Diámetro: 10 mm\n"
            "Peso: 0.42 kg por metro\n"
            "País de fabricación: México\n"
            "Uso previsto: elevación de cargas en grúas industriales"
        ),
        esperado={
            "manufacturer": "Aceros Demo del Norte",
            "model": "CAG-636-10",
            "materials": "acero galvanizado",
            "dimensions": "10",
            "weight": "0.42",
            "country_of_manufacture": "México",
            "intended_use": "elevación de cargas",
        },
        ausentes=("voltage", "power", "capacity", "brand", "sku"),
    ),
    FichaDeReferencia(
        id="sarten-inoxidable",
        texto=(
            "Sartén de acero inoxidable para cocina doméstica.\n"
            "Marca DemoCocina, modelo SX-28.\n"
            "Diámetro 28 cm. Mango de acero inoxidable remachado.\n"
            "Peso: 1.1 kg."
        ),
        esperado={
            "brand": "DemoCocina",
            "model": "SX-28",
            "materials": "acero inoxidable",
            "dimensions": "28",
            "weight": "1.1",
        },
        ausentes=("voltage", "power", "country_of_manufacture", "manufacturer", "sku"),
    ),
    FichaDeReferencia(
        id="laptop-14",
        texto=(
            "[p.1]\nCOMPUTADORA PORTÁTIL DEMOBOOK 14\n"
            "Marca: Demotec · Modelo: DB14-8\n"
            "[p.2]\nEspecificaciones eléctricas\n"
            "Adaptador: entrada 100-240 V, salida 65 W\n"
            "Memoria: 8 GB · Pantalla de 14 pulgadas\n"
            "Peso: 1.4 kg\n"
            "Hecho en China"
        ),
        esperado={
            "brand": "Demotec",
            "model": "DB14-8",
            "power": "65",
            "weight": "1.4",
            "country_of_manufacture": "China",
        },
        ausentes=("materials", "composition", "capacity", "sku"),
    ),
    FichaDeReferencia(
        id="tuberia-carbono",
        texto=(
            "Tubería de acero al carbono soldada longitudinalmente, para conducción "
            "de agua industrial.\n"
            "Diámetro exterior: 168.3 mm. Espesor de pared: 7.11 mm.\n"
            "Fabricante: Tubos Demo, S.A."
        ),
        esperado={
            "materials": "acero al carbono",
            "dimensions": "168.3",
            "manufacturer": "Tubos Demo",
            "intended_use": "conducción de agua",
        },
        ausentes=("voltage", "power", "weight", "brand", "model", "country_of_manufacture"),
    ),
    FichaDeReferencia(
        id="hervidor-electrico",
        texto=(
            "Hervidor eléctrico DemoHogar HV-17.\n"
            "Capacidad: 1.7 L. Potencia: 1500 W. Alimentación: 127 V.\n"
            "Cuerpo de plástico polipropileno, base de acero inoxidable."
        ),
        esperado={
            "brand": "DemoHogar",
            "model": "HV-17",
            "capacity": "1.7",
            "power": "1500",
            "voltage": "127",
        },
        ausentes=("weight", "country_of_manufacture", "manufacturer", "sku"),
    ),
    FichaDeReferencia(
        id="playera-algodon",
        texto=(
            "Playera de punto para caballero, manga corta.\n"
            "Composición: 100 % algodón.\n"
            "Marca DemoModa. SKU PLY-M-001."
        ),
        esperado={
            "composition": "100",
            "brand": "DemoModa",
            "sku": "PLY-M-001",
        },
        ausentes=("voltage", "power", "capacity", "weight", "country_of_manufacture", "model"),
    ),
)
