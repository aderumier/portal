import React from 'react'
import { Navigate } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'

const ProtectedRoute = ({ children, requireCreator = false }) => {
  const { isAuthenticated, isGuildMember, isCreator, loading } = useAuth()

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

  if (requireCreator && !isCreator) {
    return <Navigate to="/unauthorized" replace />
  }

  return children
}

export default ProtectedRoute

