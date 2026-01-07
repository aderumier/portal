/**
 * Cache utility for API responses with TTL (Time To Live)
 */

const CACHE_PREFIX = 'api_cache_'
const SYSTEMS_CACHE_KEY = `${CACHE_PREFIX}systems`
const CACHE_TTL_MS = 12 * 60 * 60 * 1000 // 12 hours in milliseconds

/**
 * Get cached data if it exists and is still valid
 * @param {string} key - Cache key
 * @returns {object|null} Cached data or null if expired/missing
 */
export const getCachedData = (key) => {
  try {
    const cached = localStorage.getItem(key)
    if (!cached) {
      return null
    }

    const { data, timestamp } = JSON.parse(cached)
    const now = Date.now()
    const age = now - timestamp

    // Check if cache is still valid (within TTL)
    if (age < CACHE_TTL_MS) {
      return data
    } else {
      // Cache expired, remove it
      localStorage.removeItem(key)
      return null
    }
  } catch (error) {
    console.error('Error reading cache:', error)
    // If there's an error parsing, remove the corrupted cache
    localStorage.removeItem(key)
    return null
  }
}

/**
 * Store data in cache with timestamp
 * @param {string} key - Cache key
 * @param {object} data - Data to cache
 */
export const setCachedData = (key, data) => {
  try {
    const cacheEntry = {
      data,
      timestamp: Date.now()
    }
    localStorage.setItem(key, JSON.stringify(cacheEntry))
  } catch (error) {
    console.error('Error writing cache:', error)
    // If storage is full, try to clear old cache entries
    try {
      const keys = Object.keys(localStorage)
      const cacheKeys = keys.filter(k => k.startsWith(CACHE_PREFIX))
      // Remove oldest cache entries if we can't write
      if (cacheKeys.length > 0) {
        localStorage.removeItem(cacheKeys[0])
        // Retry
        localStorage.setItem(key, JSON.stringify(cacheEntry))
      }
    } catch (retryError) {
      console.error('Failed to clear cache and retry:', retryError)
    }
  }
}

/**
 * Clear cached systems data
 */
export const clearSystemsCache = () => {
  localStorage.removeItem(SYSTEMS_CACHE_KEY)
}

/**
 * Get cached systems or fetch from API if cache expired
 * @param {Function} fetchFunction - Function that returns a Promise with the API response
 * @returns {Promise<Array>} Systems array
 */
export const getSystemsWithCache = async (fetchFunction) => {
  // Try to get from cache first
  const cachedSystems = getCachedData(SYSTEMS_CACHE_KEY)
  if (cachedSystems) {
    return cachedSystems
  }

  // Cache miss or expired, fetch from API
  const response = await fetchFunction()
  const systems = response.data?.systems || response.systems || []

  // Store in cache
  if (systems.length > 0) {
    setCachedData(SYSTEMS_CACHE_KEY, systems)
  }

  return systems
}

