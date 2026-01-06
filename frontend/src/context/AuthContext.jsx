import React, { createContext, useContext, useState, useEffect } from 'react'
import client from '../api/client'

const AuthContext = createContext(null)

export const useAuth = () => {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider')
  }
  return context
}

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    // Check if user is authenticated
    checkAuth()
  }, [])

  const checkAuth = async () => {
    try {
      const response = await client.get('/api/auth/me')
      setUser(response.data)
    } catch (error) {
      // 401 is expected for unauthenticated users, don't treat it as an error
      if (error.response?.status === 401) {
        setUser(null)
      } else {
        // For other errors, still set user to null but log the error
        console.error('Auth check error:', error)
        setUser(null)
      }
    } finally {
      setLoading(false)
    }
  }

  const login = () => {
    // Use relative URL so it works with nginx proxy
    window.location.href = '/api/auth/login'
  }

  const logout = async () => {
    try {
      await client.get('/api/auth/logout')
    } catch (error) {
      console.error('Logout error:', error)
    } finally {
      setUser(null)
      window.location.href = '/'
    }
  }

  const value = {
    user,
    loading,
    isAuthenticated: !!user,
    isGuildMember: user?.is_guild_member || false,
    isDownload: user?.is_download || false,
    isFastDownload: user?.is_fastdownload || false,
    isAdmin: user?.is_admin || false,
    // Legacy support - keep isCreator for backward compatibility
    isCreator: user?.is_admin || false,
    login,
    logout,
    refreshAuth: checkAuth,
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

