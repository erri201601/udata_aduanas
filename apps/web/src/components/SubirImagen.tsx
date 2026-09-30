/**
 * Subir una imagen y extraer de ella el Product DNA (§16, §48 primer eslabón).
 *
 * LO QUE ESTE CONTROL TIENE QUE DECIR, Y NO ES EL ÉXITO
 *
 * El caso interesante no es que funcione: es que el proveedor de visión no
 * esté configurado. La API responde 503 diciendo CUÁL falta, y ese texto tiene
 * que llegar entero a la pantalla. Un «error al subir» genérico deja a quien
 * lo ve sin saber si el problema es su imagen, la red o una llave en un `.env`
 * al que quizá ni tiene acceso.
 *
 * Y SE DICE DÓNDE QUEDÓ EL CRUDO
 *
 * El hash del archivo no es un detalle técnico de adorno: es lo único que
 * prueba, meses después, que el atributo salió de ESA foto y no de otra. Por
 * eso se enseña al terminar, aunque ocupe.
 */

import { useRef, useState } from 'react'

import { extraerDnaDeImagen } from '../api/client'
import type { DnaDesdeImagen } from '../api/client'

interface Props {
  productId: string
  /** Se llama al terminar, para que la pantalla recargue el DNA nuevo. */
  onExtraido?: () => void
}

export function SubirImagen({ productId, onExtraido }: Props) {
  const entrada = useRef<HTMLInputElement>(null)
  const [subiendo, setSubiendo] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [resultado, setResultado] = useState<DnaDesdeImagen | null>(null)

  async function alElegir(evento: React.ChangeEvent<HTMLInputElement>) {
    const imagen = evento.target.files?.[0]
    if (!imagen) return

    setSubiendo(true)
    setError(null)
    setResultado(null)
    try {
      const salida = await extraerDnaDeImagen(productId, imagen)
      setResultado(salida)
      onExtraido?.()
    } catch (causa: unknown) {
      setError(causa instanceof Error ? causa.message : 'No se pudo subir la imagen')
    } finally {
      setSubiendo(false)
      // Se limpia para poder subir DOS VECES la misma imagen: sin esto el
      // input no dispara `change` la segunda vez y parece que se colgó.
      if (entrada.current) entrada.current.value = ''
    }
  }

  return (
    <div className="subir">
      <div className="subir__accion">
        <button
          className="boton"
          onClick={() => entrada.current?.click()}
          disabled={subiendo}
          type="button"
        >
          {subiendo ? 'Leyendo la imagen…' : 'Extraer de una imagen'}
        </button>
        <input
          ref={entrada}
          type="file"
          accept="image/png,image/jpeg,image/webp,image/gif"
          onChange={alElegir}
          hidden
        />
        <p className="subir__pista">
          Una foto o una ficha técnica. El archivo se guarda entero antes de
          leerlo, con su hash, para poder volver a él.
        </p>
      </div>

      {subiendo && (
        <p className="subir__estado" role="status">
          Subiendo el archivo y pidiéndole al modelo que lo lea. Tarda unos
          segundos.
        </p>
      )}

      {error && (
        <div className="alerta" role="alert">
          <strong>No se pudo extraer el DNA de la imagen.</strong>
          {/* El texto de la API, ENTERO. Es donde dice qué llave falta. */}
          <p>{error}</p>
        </div>
      )}

      {resultado && (
        <div className="subir__resultado" role="status">
          <strong>
            Versión {resultado.version} del DNA, con {resultado.atributos}{' '}
            {resultado.atributos === 1 ? 'atributo' : 'atributos'}.
          </strong>
          {resultado.summary && <p>{resultado.summary}</p>}

          {/* Cero atributos NO es un fallo: es que en la imagen no había nada
              que el modelo pudiera afirmar. Decirlo evita que se lea como que
              la subida falló. */}
          {resultado.atributos === 0 && (
            <p>
              El modelo no pudo afirmar ningún atributo de esta imagen. No es un
              error de la subida: el archivo está guardado y su hash consta.
            </p>
          )}

          {resultado.missing_information.length > 0 && (
            <p>
              Sigue faltando:{' '}
              {resultado.missing_information.map((m) => (
                <code key={m}>{m}</code>
              ))}
            </p>
          )}

          <p className="subir__huella">
            <span>Crudo en</span> <code>{resultado.minio_key}</code>
            <br />
            <span>Hash</span> <code>{resultado.content_hash}</code>
          </p>
        </div>
      )}
    </div>
  )
}
