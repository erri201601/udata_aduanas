"""Fragmento REAL (verbatim) del Apéndice 8 del Anexo 22 RGCE 2026, extraído
con `pdftotext -layout` del PDF publicado en el DOF el 15-ene-2026.

Incluye: el encabezado de columnas ("Clave Nivel Supuestos de Aplicación...",
que no debe leerse como entrada), cuatro entradas normales con nivel "G"
(AC, AE, AF, AG -- una de ellas, AF, con espacio antes del guión), el ruido
institucional "DIARIO OFICIAL" repetido entre páginas, una entrada (AI) cuyo
"Complemento 1" trae una lista jerárquica numerada con incisos ("1. No
aplica. 2. Ley Aduanera: a) Artículo 84-A... b) Otros. 3. IGI: a) Carne de
pollo...") que NO debe confundirse con encabezados de entrada nuevos, y una
entrada (A1) de las 10 sin columna "Nivel" -- encadena directo a "Para A1
señalar:".
"""

APENDICE_8_FRAGMENTO = [
    "                                                                       Identificadores\n",
    "\n",
    "\n",
    "           Clave           Nivel      Supuestos de Aplicación                 Complemento 1                        Complemento 2        Complemento 3\n",
    "AC- Almacén general de G           Identificar a un almacén general Número       de registro como No asentar datos. (Vacío).            No asentar datos.\n",
    "    depósito certificado.          de depósito certificado.         almacén general de depósito                                         (Vacío).\n",
    "                                                                    certificado.\n",
    "AE- Empresa de comercio G          Declarar la autorización de Número de autorización de No asentar datos. (Vacío).                     No asentar datos.\n",
    "    exterior.                      empresa de comercio exterior. empresa de comercio exterior.                                          (Vacío).\n",
    "AF - Activo fijo.          G       Identificar  el   activo  fijo, No asentar datos. (Vacío).              No asentar datos. (Vacío).   No asentar datos.\n",
    "                                   únicamente cuando la clave de                                                                        (Vacío).\n",
    "                                   documento no sea exclusiva\n",
    "                                   para dicha mercancía.\n",
    "AG- Almacén general de G           Identificar a un almacén general Clave de almacén general de No asentar datos. (Vacío).              No asentar datos.\n",
    "    depósito fiscal.               de depósito.                     depósito.                                                           (Vacío).\n",
    "\n",
    "\n",
    "\n",
    "\n",
    "                                                                                                                                                            DIARIO OFICIAL\n",
    "AI-   Operaciones        de G      Declarar     operaciones       de Número del expediente y año del       Declarar el tipo del acto No asentar datos.\n",
    "      comercio exterior con        comercio exterior que se realizan amparo, el número del juzgado         reclamado:                     (Vacío).\n",
    "      amparo.                      con amparo.                       que conoce el amparo; la clave        1.   No aplica.\n",
    "                                                                     del municipio y de la entidad         2.   Ley Aduanera:\n",
    "                                                                     federativa donde se localiza dicho\n",
    "                                                                     juzgado; y el tipo de resolución           a)   Artículo 84-A y 86-A\n",
    "                                                                     que se presenta para el despacho           b)   Otros.\n",
    "                                                                     aduanero,     conforme     a     lo   3.   IGI:\n",
    "                                                                     siguiente:                                 a)   Carne de pollo.\n",
    "                                                                         SP: Suspensión provisional.           b)   Pescado.\n",
    "                                                                         SD: Suspensión definitiva.            c)   Carne de ovino.\n",
    "                                                                         AC: Amparo concedido.                 d)   Carne de bovino.\n",
    "                                                                                                                e)   Otros.\n",
    "A1- Certificado Fitozoosanitario         Para A1 señalar:                      No asentar datos.\n",
    "    y Certificado de Sanidad             1.    Se trata de productos (Vacío).                      192\n",
    "    Acuícola de Importación                    químicos, farmacéuticos y\n",
    "    (Acuerdo que establece las                 biológicos para uso en\n",
    "    mercancías               cuya              animales            acuáticos.\n",
    "    importación está sujeta a                  (Anexo 1, inciso a).\n",
]
