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
 * EL TÉRMINO DE LA FICHA SE ELIGE, NO SE TECLEA (César, 5-oct)
 *
 * El motor no puede elegirlo —lo intentó por heurística dos veces y las dos
 * produjo basura, «¿es "caja 12 unidades" lo mismo que "Lana de hierro o
 * acero"?»— así que lo elige la persona. Pero la primera versión lo pedía
 * TECLEADO, y el primer clasificador que la usó escribió
 *
 *     material = "acero al carbono"
 *
 * copiando el formato que esta misma pantalla le enseñaba debajo del campo. Con
 * eso la respuesta quedó **inerte**: para aplicarse, todas las palabras del
 * término tienen que estar en la ficha, y «material» no está — la ficha guarda
 * los VALORES de los hechos, no los nombres de los campos.
 *
 * Su respuesta se guardó firmada, con un razonamiento correcto, y no descartaba
 * nada. La pantalla dijo «guardado y firmado» y el efecto fue cero. Eso es lo
 * peor que puede hacer este formulario: gastar el minuto de un clasificador sin
 * que se note.
 *
 * Ahora los valores de la ficha son botones. Se elige uno y ya está. Queda el
 * campo libre para cuando ninguno sirva, pero deja de ser el camino por
 * defecto.
 */

import { useState } from 'react'

import { ApiError, responderVocabulario } from '../api/client'

interface Props {
  /** Lo que exige la posición, tal cual lo dice la tarifa. */
  exige: string
  /** La posición sobre la que se pregunta, para el aviso de confirmación. */
  codigo: string
  /** Las fichas compactas, de donde salen los valores elegibles.
   *
   * Una o varias: en la bandeja agrupada, los casos de una misma pregunta
   * pueden traer fichas distintas, y el término se elige de entre todas. */
  mercancia: string | string[]
  /** Se llama al guardar, con cuántos casos quedaron recalculándose.
   *
   * La bandeja de arriba tiene que volver a pedirse: los casos que esta
   * respuesta desatasque dejan de estar pendientes, y si la lista no se
   * refresca quien contesta ve exactamente lo mismo que antes y concluye —con
   * razón— que no ha servido de nada.
   */
  onGuardada?: (recalculando: number) => void
}

/** Los VALORES de la ficha, sin las etiquetas con las que se muestran.
 *
 * `mercancia` llega como «material = «acero al carbono» · construccion =
 * «6x19»». Lo que sirve como término comercial es el valor, no la etiqueta:
 * «material» no aparece en la ficha y una respuesta sobre esa palabra no se
 * aplica nunca.
 */
function valoresDe(mercancia: string | string[]): string[] {
  const fichas = Array.isArray(mercancia) ? mercancia : [mercancia]
  const valores = fichas
    .flatMap((ficha) => ficha.split('·'))
    .map((trozo) => {
      const igual = trozo.indexOf('=')
      const valor = igual >= 0 ? trozo.slice(igual + 1) : trozo
      return valor.replace(/[«»"']/g, '').trim()
    })
    .filter((v) => v.length >= 2)
  // Sin repetir: varias fichas de cable dicen todas «acero», y un botón por
  // ficha sería ruido — además de una clave duplicada para React.
  return [...new Set(valores)]
}

type Estado =
  | { fase: 'pregunta' }
  | { fase: 'guardando' }
  | { fase: 'guardado'; recalculando: number; total: number }
  | { fase: 'ya_contestada' }
  | { fase: 'error'; mensaje: string }

export function ContestarPregunta({ exige, codigo, mercancia, onGuardada }: Props) {
  const [terminoFicha, setTerminoFicha] = useState('')
  const [quien, setQuien] = useState('')
  const [nota, setNota] = useState('')
  const [estado, setEstado] = useState<Estado>({ fase: 'pregunta' })

  const listo = terminoFicha.trim().length >= 2 && quien.trim().length >= 1

  async function contestar(sonLoMismo: boolean) {
    setEstado({ fase: 'guardando' })
    try {
      const guardada = await responderVocabulario({
        termino_ficha: terminoFicha.trim(),
        termino_tarifa: exige,
        son_lo_mismo: sonLoMismo,
        reviewer: quien.trim(),
        nota: nota.trim() || null,
      })
      setEstado({
        fase: 'guardado',
        recalculando: guardada.recalculando,
        total: guardada.de_un_total,
      })
      onGuardada?.(guardada.recalculando)
    } catch (causa) {
      /* UN 409 AQUÍ NO ES UN ERROR (Persona 1, 6-oct)
         La respuesta se guarda por (término de la ficha, cláusula), sin
         posición. Si dos tarjetas comparten la cláusula, contestar la primera
         contesta la segunda, y volver a mandarla da 409. Decir «no se guardó»
         haría creer que hay que repetirla. */
      if (causa instanceof ApiError && causa.status === 409) {
        setEstado({ fase: 'ya_contestada' })
        onGuardada?.(0)
        return
      }
      setEstado({
        fase: 'error',
        mensaje: causa instanceof Error ? causa.message : 'No se pudo guardar',
      })
    }
  }

  if (estado.fase === 'ya_contestada') {
    return (
      <p className="contestar__guardado" role="status">
        Ya estaba contestada con ese mismo término: alguien la respondió antes,
        quizá desde otra tarjeta con la misma cláusula. No hace falta repetirla.
      </p>
    )
  }

  if (estado.fase === 'guardado') {
    /* Antes decía «para que surta efecto hay que reclasificar», y
       reclasificar lo hacía una persona a mano desde una terminal: en la
       práctica no se reclasificaba nunca y la respuesta no movía nada. Ahora
       el recálculo lo lanza el propio endpoint y aquí se dice cuántos casos
       son, porque es la única forma de que quien contesta sepa que su minuto
       sirvió para algo. */
    return (
      <p className="contestar__guardado" role="status">
        Guardado y firmado. El motor no vuelve a preguntar esto — ni en este
        caso ni en los iguales.{' '}
        {estado.recalculando > 0 ? (
          <>
            Recalculando {estado.recalculando} caso
            {estado.recalculando === 1 ? '' : 's'}
            {estado.total > estado.recalculando
              ? ` de ${estado.total}; el resto en la siguiente pasada`
              : ''}
            . Cuenta todos los casos que preguntaban esta cláusula, también los
            de otras posiciones: la respuesta no lleva posición. La bandeja se
            actualiza al terminar.
          </>
        ) : (
          'Ningún caso pendiente dependía de esta pregunta.'
        )}
      </p>
    )
  }

  return (
    <div className="contestar">
      <div className="contestar__campo">
        <span>¿Qué parte de la ficha estás mirando?</span>
        {/* Botones y no un campo de texto: el primero que lo usó teclëó la
            etiqueta —«material = "acero al carbono"»— y la respuesta quedó
            inerte, porque «material» no aparece en la ficha. */}
        <div className="contestar__valores">
          {valoresDe(mercancia).map((valor) => (
            <button
              type="button"
              key={valor}
              className={`contestar__valor${terminoFicha === valor ? ' contestar__valor--puesto' : ''}`}
              onClick={() => setTerminoFicha(valor)}
            >
              {valor}
            </button>
          ))}
        </div>
        <input
          type="text"
          value={terminoFicha}
          onChange={(e) => setTerminoFicha(e.target.value)}
          placeholder="…o escríbelo, si ninguno sirve"
          maxLength={120}
        />
        <small>
          Elige el dato que estás comparando. De eso depende a qué fichas se
          aplica tu respuesta: cuanto más general, a más alcanza.
        </small>
      </div>

      <label className="contestar__campo">
        <span>Tu nombre</span>
        <input
          type="text"
          value={quien}
          onChange={(e) => setQuien(e.target.value)}
          placeholder="Tu nombre"
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
          placeholder="Por qué sí o por qué no"
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
        La pregunta sale de <code>{codigo}</code>, pero tu respuesta se guarda
        sobre la cláusula, sin posición: vale para <strong>todas</strong> las
        fichas que digan el término que elijas, en cualquier posición que exija
        esa frase.
      </p>
    </div>
  )
}
