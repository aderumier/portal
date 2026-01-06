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
    // Don't redirect on 401 for auth check endpoints (they're expected to fail for unauthenticated users)
    const isAuthCheck = error.config?.url?.includes('/api/auth/me')
    
    if (error.response?.status === 401 && !isAuthCheck) {
      // Only redirect to login if not already on login page and not checking auth status
      if (window.location.pathname !== '/login' && window.location.pathname !== '/') {
        window.location.href = '/login'
      }
    }
    return Promise.reject(error)
  }
)

export default client

