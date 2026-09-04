/**
 * Configuración del cliente web.
 *
 * La URL de la API sale del entorno (§40: nada de secretos ni endpoints
 * hardcodeados). El valor por defecto es la IP Tailscale del dev server de
 * Persona 1, que es donde corre la infraestructura del equipo.
 */

const RAW_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ?? 'http://100.86.182.104:8080'

/** Base de la API, sin diagonal final. */
export const API_BASE_URL = RAW_BASE_URL.replace(/\/+$/, '')

/** Cada cuánto se vuelve a consultar el readiness, en milisegundos. */
export const HEALTH_POLL_MS = 15_000
