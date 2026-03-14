// Use relative URL in production (via nginx) or explicit URL from env
// If VITE_API_URL is not set, use relative URL (empty string) for nginx proxy
// This allows the frontend to work with nginx on port 443
// In production, ignore localhost:8000 URLs and use relative URLs instead
const envApiUrl = import.meta.env.VITE_API_URL || ''
const isProduction = import.meta.env.PROD
const isLocalhost = envApiUrl.includes('localhost:8000') || envApiUrl.includes('127.0.0.1:8000')

// In production, always use relative URLs (for nginx proxy)
// In development, use VITE_API_URL if set, otherwise use relative URLs
export const API_URL = (isProduction && isLocalhost) ? '' : envApiUrl

// Media cache busting: set from catalog systems/refresh response; appended as ?v= to media URLs
let mediaVersion = null

export const setMediaVersion = (version) => {
  mediaVersion = version == null ? null : Number(version)
}

export const getMediaVersion = () => mediaVersion

/**
 * Get the media URL for a given media path.
 * In development, this uses the Vite proxy (/media).
 * In production, this uses the full API URL.
 * Appends ?v= when mediaVersion is set (cache busting after catalog refresh).
 */
export const getMediaUrl = (mediaPath) => {
  if (!mediaPath) return null
  const base = `/media/${mediaPath}`
  return mediaVersion != null ? `${base}?v=${mediaVersion}` : base
}

/**
 * Check if nginx is serving the application (ports 443, 80, or HTTPS without port)
 * @returns {boolean} True if nginx is likely serving the app
 */
const isNginxServing = () => {
  if (typeof window === 'undefined') return false

  const port = window.location.port
  const protocol = window.location.protocol

  // Nginx typically serves on:
  // - Port 443 (HTTPS, default)
  // - Port 80 (HTTP, default)
  // - No port specified (default ports)
  // - HTTPS protocol (usually nginx with SSL)
  return (
    port === '' ||
    port === '443' ||
    port === '80' ||
    protocol === 'https:'
  )
}

/**
 * Get the thumbnail URL for a given media path with specified dimensions.
 * Uses nginx image_filter module to resize images dynamically.
 * Only uses thumbnails when nginx is serving (ports 443/80 or HTTPS).
 * Falls back to regular media URL in development.
 * @param {string} mediaPath - The path to the media file (e.g., "macintosh/media/thumbnails/game.png")
 * @param {number} width - Thumbnail width in pixels
 * @param {number} height - Thumbnail height in pixels
 * @returns {string|null} The thumbnail URL or regular media URL, or null if mediaPath is invalid
 */
export const getThumbnailUrl = (mediaPath, width, height) => {
  if (!mediaPath) return null

  // Only use thumbnail URLs when nginx is serving (ports 443/80 or HTTPS)
  // In development (port 3000), use regular media URLs (Vite proxy doesn't support image_filter)
  if (isNginxServing()) {
    // URL format: /media/thumbnail/WIDTHxHEIGHT/system/media/thumbnails/image.png
    const base = `/media/thumbnail/${width}x${height}/${mediaPath}`
    return mediaVersion != null ? `${base}?v=${mediaVersion}` : base
  }
  return getMediaUrl(mediaPath)
}

