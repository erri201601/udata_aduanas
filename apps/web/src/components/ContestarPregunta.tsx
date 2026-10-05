/**
 * El formulario con el que un clasificador contesta una pregunta de desempate.
 *
 * LO QUE FALTABA, Y SIN ESTO NADA DE LO DEMÁS SERVÍA
 *
 * El motor generaba la pregunta, esta pantalla la mostraba, la base sabía
 * guardarla y el motor sabía usarla. No había dónde contestarla. Un
 * clasificador tenía que mandar su respuesta por un chat y que alguien la
 * metiera a mano con `curl` — y una cadena así no se usa dos veces.
 *
 * EL «NO» ES UN BOTÓN IGUAL DE GRANDE QUE EL «SÍ»
 *
 * Y no es estética: el «no» es lo que DESCARTA una posición y deja al motor
 * con dos candidatas en vez de nueve. Hacerlo secundario empujaría a contestar
 * sí, que es la respuesta que menos informa.
 *
 * EL TÉRMINO DE LA FICHA LO ESCRIBE LA PERSONA
 *
 * A propósito. El motor intentó elegirlo por heurística dos veces y las dos
 * produjo basura —«¿es "caja 12 unidades" lo mismo que "Lana de hierro o
 * acero"?»—. Quien contesta sabe cuál de los datos de la ficha está mirando, y
 * teclearlo le cuesta tres segundos.
 */

import { useState } from 'react'

import { responderVocabulario } from '../api/client'

interface Props {
  /** Lo que exige la posición, tal cual lo dice la tarifa. */
  exige: string
  /** La posición sobre la que se pregunta, para el aviso de confirmación. */
  codigo: string
  /** La ficha compacta, de donde la persona saca el término. */
  mercancia: string
}

type Estado = { fase: 'pregunta' } | { fase: 'guardando' } | { fase: 'guardado' } | { fase: 'error'; mensaje: string }

export function ContestarPregunta({ exige, codigo, mercancia }: Props) {
  const [terminoFicha, setTerminoFicha] = useState('')
  const [quien, setQuien] = useState('')
  const [nota, setNota] = useState('')
  const [estado, setEstado] = useState<Estado>({ fase: 'pregunta' })

  const listo = terminoFicha.trim().length >= 2 && quien.trim().length >= 1

  async function contestar(sonLoMismo: boolean) {
    setEstado({ fase: 'guardando' })
    try {
      await responderVocabulario({
        termino_ficha: terminoFicha.trim(),
        termino_tarifa: exige,
        son_lo_mismo: sonLoMismo,
        reviewer: quien.trim(),
        nota: nota.trim() || null,
      })
      setEstado({ fase: 'guardado' })
    } catch (causa) {
      setEstado({
        fase: 'error',
        mensaje: causa instanceof Error ? causa.message : 'No se pudo guardar',
      })
    }
  }

  if (estado.fase === 'guardado') {
    return (
      <p className="contestar__guardado" role="status">
        Guardado y firmado. El motor no vuelve a preguntar esto — ni en este
        caso ni en los iguales. Para que surta efecto hay que reclasificar.
      </p>
    )
  }

  return (
    <div className="contestar">
      <label className="contestar__campo">
        <span>¿Qué parte de la ficha estás mirando?</span>
        <input
          type="text"
          value={terminoFicha}
          onChange={(e) => setTerminoFicha(e.target.value)}
          placeholder="6x19"
          maxLength={120}
        />
        <small>{mercancia}</small>
      </label>

      <label className="contestar__campo">
        <span>Tu nombre</span>
        <input
          type="text"
          value={quien}
          onChange={(e) => setQuien(e.target.value)}
          placeholder="César"
          maxLength={64}
        />
        {/* Sin nombre no es criterio, es una opinión anónima — y esto va a
            sostener una fracción que alguien firma. */}
        <small>Queda en la traza: esto sostiene una clasificación.</small>
      </label>

      <label className="contestar__campo">
        <span>Por qué, en una línea</span>
        <input
          type="text"
          value={nota}
          onChange={(e) => setNota(e.target.value)}
          placeholder="6x19 son 6 torones de 19 alambres: 114, no 7."
        />
        <small>Lo lee quien audite una decisión apoyada en tu respuesta.</small>
      </label>

      <div className="contestar__botones">
        <button
          type="button"
          className="boton boton--si"
          disabled={!listo || estado.fase === 'guardando'}
          onClick={() => contestar(true)}
        >
          Sí, es lo mismo
        </button>
        <button
          type="button"
          className="boton boton--no"
          disabled={!listo || estado.fase === 'guardando'}
          onClick={() => contestar(false)}
        >
          No, no lo es
        </button>
      </div>

      {!listo && (
        <p className="contestar__pista">
          Falta el término de la ficha y tu nombre. Lo demás es opcional, pero
          el «por qué» es lo que hace auditable la respuesta.
        </p>
      )}

      {estado.fase === 'error' && (
        <p className="contestar__error" role="alert">
          No se guardó: {estado.mensaje}. La respuesta no se pierde si la
          vuelves a enviar — el servidor rechaza duplicados, así que reintentar
          es seguro.
        </p>
      )}

      <p className="contestar__alcance">
        Tu respuesta se guarda sobre <code>{codigo}</code> y vale para{' '}
        <strong>todas</strong> las fichas que digan lo mismo, no sólo para ésta.
      </p>
    </div>
  )
}
