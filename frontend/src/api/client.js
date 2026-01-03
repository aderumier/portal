import axios from 'axios'
import { API_URL } from '../utils/constants'

const client = axios.create({
  baseURL: API_URL,
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

