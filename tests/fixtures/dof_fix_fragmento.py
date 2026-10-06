"""Fragmento real del HTML público de
`https://dof.gob.mx/indicadores_detalle.php?cod_tipo_indicador=158` para el
rango 01/10/2026 a 06/10/2026, descargado el 2026-10-06. Recorte del bloque
"DOLAR" completo (encabezado + las 4 filas reales que trae ese rango -- el
03 y 04 de octubre son sábado y domingo, sin fila propia, tal como el
documento real los omite).

Normalizado sólo en espacios en blanco (tabs -> espacio, sin espacios
colgantes a final de línea) para que ruff no lo trate como código mal
formateado -- ninguna etiqueta, atributo o texto real cambió.
"""

FIX_FRAGMENTO_REAL = """\
<table  width="95%" border="0" cellspacing="0" cellpadding="0" align="center">
<tr>
    <td class="txt_blanco" style="padding-left:4px" bgcolor="#737373">DOLAR</td>
  </tr>
  <tr>
    <td>
  <table width="100%" border="0" cellspacing="0" cellpadding="2" >
   <tr>
    <td class="txt" height="17" style="padding: 10px;"><b>FECHA</b></td>
   </tr>
   <tr>
    <td  class="txt" height="17" style="padding: 10px;">01/10/2026 a 06/10/2026</td>
   </tr>
   <tr>
    <td height="20">&nbsp;</td>
   </tr>
  </table>
 </td>
  </tr>
  <tr>
    <td>
 <table width="70%" border="0" cellspacing="0" cellpadding="0" class="Tabla_borde" align="center" style="border:1px solid #b2b2b2" bgcolor="#FFFFFF">
        <tr class="txt_blanco" bgcolor="#b2b2b2">
          <td height="17" width="48%" align="center" style="padding: 5px;">Fecha</td>
          <td height="17" width="52%" align="center" style="padding: 5px;">Valor</td>
        </tr>
           <tr class="Celda 1">
     <td height="17" width="48%" align="center" class="txt" style="padding: 3px;">01-10-2026</td>
     <td width="52%" align="center" class="txt">18.069200</td>
   </tr>
     <tr class="Celda 1">
     <td height="17" width="48%" align="center" class="txt" style="padding: 3px;">02-10-2026</td>
     <td width="52%" align="center" class="txt">18.368800</td>
   </tr>
     <tr class="Celda 1">
     <td height="17" width="48%" align="center" class="txt" style="padding: 3px;">05-10-2026</td>
     <td width="52%" align="center" class="txt">18.190300</td>
   </tr>
     <tr class="Celda 1">
     <td height="17" width="48%" align="center" class="txt" style="padding: 3px;">06-10-2026</td>
     <td width="52%" align="center" class="txt">18.134300</td>
   </tr>
        </table>
   <br />
"""
