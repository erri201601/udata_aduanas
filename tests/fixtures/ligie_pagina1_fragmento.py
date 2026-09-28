"""Fragmento REAL (líneas verbatim) de la página 1 de
`diputados.gob.mx/LeyesBiblio/pdf/LIGIE_2022.pdf` (Texto Vigente, última
reforma DOF 29-12-2025), extraído con `pdftotext -layout -f 1 -l 1`.

Incluye el ruido institucional que se repite en cada página (encabezado
"LEY DE LOS IMPUESTOS...", "CÁMARA DE DIPUTADOS...", "TEXTO VIGENTE"...) y
el arranque del cuerpo de la tarifa (Sección I, Capítulo 01) para verificar
que el parser corta justo donde debe, ni antes ni después.
"""

PAGINA_1_LIGIE = """\
                                                        LEY DE LOS IMPUESTOS GENERALES DE IMPORTACIÓN Y DE EXPORTACIÓN
               CÁMARA DE DIPUTADOS DEL H. CONGRESO DE LA UNIÓN                                     Última Reforma DOF 29-12-2025
               Secretaría General
               Secretaría de Servicios Parlamentarios




        LEY DE LOS IMPUESTOS GENERALES DE IMPORTACIÓN Y DE EXPORTACIÓN
                   Nueva Ley publicada en el Diario Oficial de la Federación el 7 de junio de 2022

                                                              TEXTO VIGENTE
                                                 Última reforma publicada DOF 29-12-2025

                     Fracciones arancelarias de la Tarifa de la Ley modificadas por Decreto DOF 23-04-2026




Al margen un sello con el Escudo Nacional, que dice: Estados Unidos Mexicanos.- Presidencia de la
República.

   ANDRÉS MANUEL LÓPEZ OBRADOR, Presidente de los Estados Unidos Mexicanos, a sus
habitantes sabed:

   Que el Honorable Congreso de la Unión, se ha servido dirigirme el siguiente

                                                                 DECRETO

   "EL CONGRESO GENERAL DE LOS ESTADOS UNIDOS MEXICANOS, DECRETA:

   SE EXPIDE LA LEY DE LOS IMPUESTOS GENERALES DE IMPORTACIÓN Y DE EXPORTACIÓN

   Artículo Único. Se expide la Ley de los Impuestos Generales de Importación y de Exportación

        LEY DE LOS IMPUESTOS GENERALES DE IMPORTACIÓN Y DE EXPORTACIÓN

   Artículo 1o.- Se establecen las cuotas que, atendiendo a la clasificación de la mercancía, servirán
para determinar los Impuestos Generales de Importación y de Exportación, de conformidad con la
siguiente:
                                                                  TARIFA

                                            Sección I
                         ANIMALES VIVOS Y PRODUCTOS DEL REINO ANIMAL

   Notas.

   1.    En esta Sección, cualquier referencia a un género o a una especie determinada de un animal se
         aplica también, salvo disposición en contrario, a los animales jóvenes de ese género o de esa
         especie.

   2.    Salvo disposición en contrario, cualquier referencia en la Nomenclatura a productos secos o
         desecados alcanza también a los productos deshidratados, evaporados o liofilizados.

                                                               Capítulo 01
                                                              Animales vivos

   Nota.

   1.    Este Capítulo comprende todos los animales vivos, excepto:




                                                                   1 de 893
"""
