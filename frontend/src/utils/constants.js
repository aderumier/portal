export const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

/**
 * Get the media URL for a given media path.
 * In development, this uses the Vite proxy (/media).
 * In production, this uses the full API URL.
 */
export const getMediaUrl = (mediaPath) => {
  if (!mediaPath) return null
  // Use relative URL to leverage Vite proxy in development
  // In production, this will need to be configured based on deployment
  return `/media/${mediaPath}`
}

