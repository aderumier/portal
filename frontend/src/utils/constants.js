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

// Media cache busting.
// Per-system version tokens (keyed by catalog type, then system id) let us bust
// the browser cache only for systems whose media actually changed, instead of
// stamping a new global value onto every image URL on each catalog regeneration.
//   - releases: snapshot/version name (stable until a new snapshot is published)
//   - wip: gamelist.xml modification date (changes only when the gamelist does)
// Set from the catalog systems response (media_versions). The legacy global
// mediaVersion (catalog timestamp) is kept as a fallback for system logos and
// for any media whose system has no per-system token.
const mediaVersions = { wip: {}, releases: {} }
let mediaVersion = null

export const setMediaVersion = (version) => {
  mediaVersion = version == null ? null : Number(version)
}

export const getMediaVersion = () => mediaVersion

export const setMediaVersions = (catalogType, map) => {
  const key = catalogType === 'wip' ? 'wip' : 'releases'
  mediaVersions[key] = (map && typeof map === 'object') ? map : {}
}

// Media paths always start with the system id (e.g. "macintosh/media/...").
const systemIdFromPath = (mediaPath) => {
  const slash = mediaPath.indexOf('/')
  return slash === -1 ? mediaPath : mediaPath.slice(0, slash)
}

// Resolve the cache-busting token for a media path: prefer the per-system token
// for the active catalog type, fall back to the global media version.
const versionForPath = (mediaPath, catalogType) => {
  const key = catalogType === 'wip' ? 'wip' : 'releases'
  const token = mediaVersions[key][systemIdFromPath(mediaPath)]
  return token != null ? token : mediaVersion
}

const withVersion = (base, version) =>
  version != null ? `${base}?v=${encodeURIComponent(version)}` : base

/**
 * Get the system logo URL for a given system ID.
 * Logos are static assets (not catalog media), so they keep using the global
 * media version for cache busting.
 */
export const getSystemLogoUrl = (systemId) => {
  return withVersion(`/systems_logos/${systemId}.webp`, mediaVersion)
}

/**
 * Get the media URL for a given media path.
 * In development, this uses the Vite proxy (/media).
 * In production, this uses the full API URL.
 * Appends a per-system ?v= token so unchanged systems keep stable URLs.
 */
export const getMediaUrl = (mediaPath, catalogType = 'releases') => {
  if (!mediaPath) return null
  const encodedPath = mediaPath.split('/').map(encodeURIComponent).join('/')
  const base = `/media/${encodedPath}`
  return withVersion(base, versionForPath(mediaPath, catalogType))
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
export const getThumbnailUrl = (mediaPath, width, height, catalogType = 'releases') => {
  if (!mediaPath) return null

  // Only use thumbnail URLs when nginx is serving (ports 443/80 or HTTPS)
  // In development (port 3000), use regular media URLs (Vite proxy doesn't support image_filter)
  if (isNginxServing()) {
    // URL format: /media/thumbnail/WIDTHxHEIGHT/system/media/thumbnails/image.png
    const encodedPath = mediaPath.split('/').map(encodeURIComponent).join('/')
    const base = `/media/thumbnail/${width}x${height}/${encodedPath}`
    return withVersion(base, versionForPath(mediaPath, catalogType))
  }
  return getMediaUrl(mediaPath, catalogType)
}

