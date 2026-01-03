import React from 'react'
import { Navigate } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'

const ProtectedRoute = ({ children, requireDownload = false, requireAdmin = false }) => {
  const { isAuthenticated, isGuildMember, isDownload, isAdmin, loading } = useAuth()

  if (loading) {
    return (
      <div style={{
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        height: '100vh'
      }}>
        <p>Loading...</p>
      </div>
    )
  }

  if (!isAuthenticated || !isGuildMember) {
    return <Navigate to="/login" replace />
  }

  if (requireDownload && !isDownload) {
    return <Navigate to="/unauthorized" replace />
  }

  if (requireAdmin && !isAdmin) {
    return <Navigate to="/unauthorized" replace />
  }

  return children
}

export default ProtectedRoute

