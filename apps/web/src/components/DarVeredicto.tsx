/**
 * Dictaminar desde la pantalla que EXPLICA una decisión, no sólo desde la bandeja.
 *
 * Classification enseñaba la decisión y su dictamen, y no permitía actuar: se
 * podía mirar, no firmar. Y la bandeja sólo trae lo que el motor marcó, así
 * que lo que resolvió limpio y nadie miró no tenía dónde revisarse.
 *
 * LAS DOS COSAS QUE ESTA PANTALLA TIENE QUE HACER BIEN, Y LAS DOS YA FALLARON
 *
 * (a) El veredicto va a la decisión VIGENTE del caso, no a la que se pintó.
 *     El 6-oct un clasificador dictaminó desde una pestaña abierta de la
 *     víspera y su veredicto quedó colgado de una decisión que el motor ya no
 *     sostenía. Antes de enviar se pide `/classifications/{id}/vigente`; si el
 *     motor volvió a clasificar mientras se miraba, no se envía: se enseña la
 *     vigente y se pide confirmar sobre ella.
 *
 * (b) Se avisa cuando la fracción tecleada es una que el motor DESCARTÓ.
 *     Ese mismo veredicto llevaba 73121008 mientras su nota decía que era
 *     incompatible. El motivo sale de `descartadas` de la traza —código,
 *     motivo y de dónde sale—, nunca del texto del razonamiento. Las
 *     candidatas de una abstención no avisan: elegir una de ellas es justo lo
 *     que se le pide a quien revisa.
 */

import { useEffect, useState } from 'react'

import { type CasoVigente, fetchCasoVigente, revisarDecision } from '../api/client'
import { type CamposVeredicto, FormularioVeredicto, type Veredicto } from './FormularioVeredicto'

interface Descarte {
  code: string
  motivo: string
  por: 'NOTA_LEGAL' | 'MATERIA' | 'CONTRADICCION' | 'RESPUESTA_FIRMADA'
}

/** De dónde sale un descarte, dicho para quien lo lee. */
const POR: Record<Descarte['por'], string> = {
  NOTA_LEGAL: 'por una nota legal',
  MATERIA: 'por la materia',
  CONTRADICCION: 'porque la ficha contradice su texto',
  RESPUESTA_FIRMADA: 'por una respuesta firmada de un clasificador',
}

/** Todos los descartes de la traza. Las trazas anteriores al 6-oct no traen
 *  la clave: se tratan como lista vacía, que es lo que significan. */
function descartesDe(caso: CasoVigente): Descarte[] {
  const pasos = (caso.decision.rgi_trace ?? []) as { descartadas?: Descarte[] }[]
  return pasos.flatMap((p) => p.descartadas ?? [])
}

function avisoPara(caso: CasoVigente) {
  const descartes = descartesDe(caso)
  const resuelta = caso.decision.fraction_code
  return (fraccion: string): string | null => {
    // Por PREFIJO: una fracción que cuelga de una partida descartada también
    // lo está.
    const d = descartes.find((x) => fraccion.startsWith(x.code))
    if (d) return `El motor descartó ${d.code} ${POR[d.por]}: ${d.motivo}.`
    // Si el motor resolvió otra y ésta no está descartada, es un CORRIGE
    // legítimo: basta con decir qué resolvió.
    if (resuelta && fraccion.length === 8 && fraccion !== resuelta) {
      return `El motor resolvió ${resuelta}.`
    }
    return null
  }
}

function fecha(iso: string): string {
  return new Date(iso).toLocaleString('es-MX', { dateStyle: 'medium', timeStyle: 'short' })
}

interface Props {
  /** La decisión que la pantalla está explicando. */
  decisionId: string
  revisor: string
  onRevisor: (valor: string) => void
}

export function DarVeredicto({ decisionId, revisor, onRevisor }: Props) {
  const [caso, setCaso] = useState<CasoVigente | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [enviando, setEnviando] = useState(false)
  const [registrado, setRegistrado] = useState<string | null>(null)

  useEffect(() => {
    const control = new AbortController()
    fetchCasoVigente(decisionId, control.signal)
      .then(setCaso)
      .catch((causa: unknown) => {
        if (control.signal.aborted) return
        setError(causa instanceof Error ? causa.message : 'No se pudo cargar el caso')
      })
    return () => control.abort()
  }, [decisionId])

  async function enviar(veredicto: Veredicto, campos: CamposVeredicto): Promise<boolean> {
    if (!caso) return false
    setEnviando(true)
    setError(null)
    setRegistrado(null)
    try {
      // Justo antes de enviar, no al abrir la pantalla: entre una cosa y otra
      // el motor puede haber vuelto a clasificar.
      const ahora = await fetchCasoVigente(decisionId)
      if (ahora.decision.id !== caso.decision.id) {
        // No se manda: el aviso de fracción y lo que la persona leyó eran de
        // la decisión anterior. Se enseña la nueva y se vuelve a pedir.
        setCaso(ahora)
        setError(
          'El motor volvió a clasificar este caso mientras lo mirabas. Revisa la decisión vigente y vuelve a enviar.',
        )
        return false
      }
      await revisarDecision(ahora.decision.id, { veredicto, reviewer: revisor, ...campos })
      setRegistrado(`Registrado y firmado por ${revisor}.`)
      setCaso(await fetchCasoVigente(decisionId))
      return true
    } catch (causa: unknown) {
      setError(causa instanceof Error ? causa.message : 'No se pudo registrar')
      return false
    } finally {
      setEnviando(false)
    }
  }

  return (
    <section className="revision" aria-label="Dar veredicto">
      <strong>Dar veredicto</strong>

      {error && (
        <p className="revision-fila__aviso" role="alert">
          {error}
        </p>
      )}

      {caso && caso.decision.id !== decisionId && (
        <p className="revision-fila__aviso">
          Esta es una decisión anterior del caso. El motor lo volvió a clasificar el{' '}
          {fecha(caso.decision.created_at)} (
          {caso.decision.fraction_code ?? caso.decision.status}): el veredicto irá a
          esa, que es la vigente. Es la misma ficha, así que lo que digas sobre la
          mercancía sigue valiendo.
        </p>
      )}

      {caso?.dictamen_del_caso && (
        <p className="revision-fila__aviso">
          Este caso ya lo dictaminó una persona el{' '}
          {fecha(caso.dictamen_del_caso.created_at)}:{' '}
          {caso.dictamen_del_caso.fraction_code
            ? caso.dictamen_del_caso.fraction_code
            : 'falta información'}
          . Un veredicto nuevo lo sustituye: manda el último.
        </p>
      )}

      {registrado && (
        <p className="contestar__guardado" role="status">
          {registrado}
        </p>
      )}

      {caso && (
        <>
          <label className="revisor">
            <span>Quién revisa</span>
            <input
              value={revisor}
              onChange={(e) => onRevisor(e.target.value)}
              placeholder="tu nombre"
              maxLength={64}
            />
            <em>Una corrección anónima no es auditable.</em>
          </label>
          <FormularioVeredicto
            revisor={revisor}
            ocupado={enviando}
            onEnviar={enviar}
            avisoFraccion={avisoPara(caso)}
            puedeConfirmar={Boolean(caso.decision.fraction_code)}
          />
        </>
      )}
    </section>
  )
}
