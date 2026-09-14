# AJR y ANA — con quién es el proyecto

> Registrado el 14 de septiembre de 2026. La descripción viene de Persona 1
> (9-sep-2026), basada en información pública de AJR. **No está contrastada
> todavía contra una fuente almacenada**: los detalles de servicios y
> funciones de ANA quedan `NEEDS_VALIDATION` hasta que alguien los verifique
> contra material de AJR.

## Por qué existe este documento

El maestro nombra a AJR y a ANA en una docena de sitios —el objetivo del MVP,
la arquitectura, la regla de desacoplamiento— y en ninguno dice qué son. El
9 de septiembre eso produjo un error concreto: se redactó el guion de la demo
y una petición de datos asumiendo que AJR era una agencia aduanal que clasifica
con su propia firma. No lo es exactamente, y cambia el discurso.

## Qué son

| | Qué es |
|---|---|
| **AJR Comercio Exterior** | Firma mexicana de comercio exterior, aduanas y cumplimiento regulatorio. Opera desde 1990. Ofrece consultoría, logística y aduanas, administración de programas IMMEX, capacitación, aspectos legales y fiscales, y software para importadores y exportadores |
| **ANA** | *Sistema para la Administración del Comercio Exterior*. **Es software de AJR, no otra empresa** |

**ANA administra el expediente electrónico de comercio exterior** de una
empresa. Según la descripción recibida:

- recupera y organiza la información de las operaciones aduaneras
- ayuda a auditar documentos electrónicos o digitales
- obtiene acuses de valor
- genera reportes para aduanas y contabilidad
- gestiona activos fijos
- apoya con COVE y e-documents

## Cómo encaja con la arquitectura del maestro (§2)

```text
AJR / ANA           ← ANA es el sistema fuente donde viven las operaciones
    │
AJR Connector       ← el adaptador que traduce lo de ANA a nuestro modelo
    │
Canonical Data Model
    │
ADUANERO CORE       ← propiedad de UDATA, sin lógica específica de AJR
```

Con esto la regla del §2 se lee entera: **el núcleo no puede depender de ANA
porque ANA es el sistema de un cliente**, y el valor de UDATA está en que
ADUANERO CORE funcione igual sobre otra fuente.

## Lo que implica, como hipótesis

Por la descripción, ANA opera a nivel **documento y expediente**: organiza,
audita, reporta. Lo que ADUANERO OS aporta está en otra capa: **decidir y
defender la clasificación arancelaria** con las RGI, la norma vigente en la
fecha y el expediente de las diez preguntas del §49.

Si eso se confirma, la demo no compite con ANA: le añade lo que no hace. **Es
una hipótesis**, no una conclusión — está pendiente el análisis de qué hace hoy
ANA y qué le falta.

## Estado de la relación

| Fecha | Decisión |
|---|---|
| 9-sep-2026 | Se redacta la petición de diez pedimentos cerrados (`PETICION_AJR.md`) |
| 14-sep-2026 | **Persona 1 decide omitir los pedimentos por ahora**, reales y sintéticos. La petición queda en pausa, sin enviar |

## Lo que queda por verificar

- los servicios y funciones de ANA, contra material de AJR
- qué hace hoy ANA en clasificación arancelaria, si hace algo
- el formato en que ANA exporta operaciones, que es lo que define el AJR Connector
