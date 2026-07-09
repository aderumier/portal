import axios from 'axios'
import { API_URL } from '../utils/constants'

// Use API_URL if set, otherwise use relative URLs (for nginx proxy)
// Empty baseURL means requests will be relative to the current origin
const client = axios.create({
  baseURL: API_URL || '',  // Empty string = relative URLs (works with nginx)
  withCredentials: true, // Include cookies for session
  headers: {
    'Content-Type': 'application/json',
  },
})

// Request interceptor
client.interceptors.request.use(
  (config) => {
    return config
  },
  (error) => {
    return Promise.reject(error)
  }
)

// Response interceptor
client.interceptors.response.use(
  (response) => {
    return response
  },
  (error) => {
    // Don't redirect on 401 for endpoints that handle auth gracefully themselves
    const skipRedirectUrls = ['/api/auth/me', '/api/users/tokens']
    const isAuthCheck = skipRedirectUrls.some(u => error.config?.url?.includes(u))

    if (error.response?.status === 401 && !isAuthCheck) {
      // Only redirect to login if not on a page that must stay accessible without auth
      const publicPaths = ['/', '/login', '/terms-of-service', '/privacy-policy']
      if (!publicPaths.includes(window.location.pathname)) {
        window.location.href = '/login'
      }
    }
    return Promise.reject(error)
  }
)

export default client

