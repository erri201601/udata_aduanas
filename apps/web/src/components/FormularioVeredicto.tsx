/**
 * Las tres salidas de un veredicto: es correcta, corregir, falta información.
 *
 * UN SOLO FORMULARIO PARA LAS DOS PANTALLAS
 *
 * Vivía dentro de la bandeja. Cuando hizo falta dictaminar también desde la
 * pantalla que explica una decisión (Classification), copiarlo habría dejado
 * dos formularios que divergen al primer arreglo — y este formulario ya tiene
 * varios: fracción y NICO en campos separados, nota obligatoria en «falta
 * información», el NICO sólo con fracción. Se extrajo tal cual.
 *
 * EL AVISO NO BLOQUEA
 *
 * `avisoFraccion` recibe lo tecleado y devuelve un texto o nada. Existe porque
 * el 6-oct un clasificador escribió 73121008 como fracción correcta mientras
 * su propia nota decía que era incompatible: estaba describiendo el error del
 * motor y pegó el código de ahí. Un aviso lo habría parado. Pero la persona
 * manda en el criterio: se enseña y se puede guardar igual.
 */

import { useState } from 'react'

export type Veredicto = 'CONFIRMA' | 'CORRIGE' | 'FALTA_INFORMACION'

export interface CamposVeredicto {
  fraction_code: string | null
  nico_code: string | null
  nota: string | null
}

interface Props {
  /** Quién firma. Sin nombre no se puede enviar: no sería auditable. */
  revisor: string
  ocupado: boolean
  /** Devuelve `true` si se guardó, para limpiar y cerrar el formulario. */
  onEnviar: (veredicto: Veredicto, campos: CamposVeredicto) => Promise<boolean>
  /** Un aviso sobre la fracción tecleada, o `null`. Nunca impide guardar. */
  avisoFraccion?: (fraccion: string) => string | null
  /** «Es correcta» sólo tiene sentido si hay una fracción que confirmar. */
  puedeConfirmar?: boolean
}

export function FormularioVeredicto({
  revisor,
  ocupado,
  onEnviar,
  avisoFraccion,
  puedeConfirmar = true,
}: Props) {
  /** Qué formulario está abierto. Corregir pide fracción; «falta información»
   *  pide el dato que falta, y son preguntas distintas. */
  const [modo, setModo] = useState<Veredicto | null>(null)
  const [fraccion, setFraccion] = useState('')
  const [nico, setNico] = useState('')
  const [nota, setNota] = useState('')

  async function enviar(veredicto: Veredicto) {
    const guardado = await onEnviar(veredicto, {
      fraction_code: veredicto === 'CORRIGE' ? fraccion : null,
      // Sólo con fracción: un NICO suelto no identifica nada, y el endpoint lo
      // rechaza. Mandarlo igual daría un 422 que no se entendería desde aquí.
      nico_code: veredicto === 'CORRIGE' && nico ? nico : null,
      nota: nota || null,
    })
    if (guardado) {
      setModo(null)
      setFraccion('')
      setNico('')
      setNota('')
    }
  }

  const aviso = modo === 'CORRIGE' && fraccion.length >= 4 ? avisoFraccion?.(fraccion) : null

  if (modo === 'CORRIGE') {
    return (
      <div className="revision-fila__forma">
        <label>
          <span>Fracción correcta</span>
          <input
            value={fraccion}
            onChange={(e) => setFraccion(e.target.value)}
            placeholder="84713001"
            maxLength={8}
          />
        </label>
        {/* Campo propio, no los dos últimos dígitos de la fracción: son dos
            decisiones distintas y juntarlas en una caja invita a escribir
            7312100502. Opcional — se deja vacío cuando sólo se determina la
            fracción. */}
        <label>
          <span>NICO (opcional)</span>
          <input
            value={nico}
            onChange={(e) => setNico(e.target.value)}
            placeholder="02"
            maxLength={2}
          />
        </label>
        <label className="ancho">
          <span>Por qué</span>
          <input
            value={nota}
            onChange={(e) => setNota(e.target.value)}
            placeholder="Qué vio el motor que no era"
          />
        </label>
        {aviso && (
          <p className="revision-fila__aviso" role="alert">
            {aviso} ¿Seguro? Puedes guardarlo igual: el criterio es tuyo.
          </p>
        )}
        <div className="revision-fila__acciones">
          <button
            className="boton"
            onClick={() => void enviar('CORRIGE')}
            disabled={!revisor || !fraccion || ocupado}
          >
            {ocupado ? 'Guardando…' : 'Guardar corrección'}
          </button>
          <button className="boton boton--plano" onClick={() => setModo(null)}>
            Cancelar
          </button>
        </div>
      </div>
    )
  }

  if (modo === 'FALTA_INFORMACION') {
    return (
      <div className="revision-fila__forma">
        {/* Sin campo de fracción a propósito: lo que se está declarando es que
            no se puede determinar. */}
        <label className="ancho">
          <span>Qué dato falta</span>
          <input
            value={nota}
            onChange={(e) => setNota(e.target.value)}
            placeholder="El diámetro exterior: sin él no se separan 730511 y 730519"
          />
        </label>
        <div className="revision-fila__acciones">
          <button
            className="boton"
            onClick={() => void enviar('FALTA_INFORMACION')}
            disabled={!revisor || !nota.trim() || ocupado}
          >
            {ocupado ? 'Guardando…' : 'Guardar: hay que pedir el dato'}
          </button>
          <button className="boton boton--plano" onClick={() => setModo(null)}>
            Cancelar
          </button>
        </div>
        <p className="revision-fila__aviso">
          El caso sale de la bandeja y queda pidiendo este dato. No vuelve a
          aparecer para que nadie repita la misma conclusión.
        </p>
      </div>
    )
  }

  /* Confirmar y corregir cuestan lo mismo: un clic cada uno. Si aceptar fuera
     más barato, la bandeja se vaciaría sin leer. */
  return (
    <div className="revision-fila__acciones">
      {puedeConfirmar && (
        <button
          className="boton boton--plano"
          onClick={() => void enviar('CONFIRMA')}
          disabled={!revisor || ocupado}
        >
          Es correcta
        </button>
      )}
      <button
        className="boton boton--plano"
        onClick={() => setModo('CORRIGE')}
        disabled={!revisor}
      >
        Corregir
      </button>
      {/* La tercera salida. Cuesta lo mismo que las otras dos: si fuera más
          barata se convertiría en la vía de escape de los casos difíciles. */}
      <button
        className="boton boton--plano"
        onClick={() => setModo('FALTA_INFORMACION')}
        disabled={!revisor}
      >
        Falta información
      </button>
    </div>
  )
}
