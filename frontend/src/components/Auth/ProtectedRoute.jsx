import React from 'react'
import { Navigate } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'
import { useCatalog } from '../../context/CatalogContext'

const ProtectedRoute = ({ children, requireDownload = false, requireAdmin = false, requireContribute = false, requireReleases = false, requireWip = false }) => {
  const { isAuthenticated, isGuildMember, isDownload, isFastDownload, isAdmin, loading } = useAuth()
  const { canContribute, canViewReleases, canViewWip, loading: catalogLoading } = useCatalog()

  const needsCatalog = requireContribute || requireReleases || requireWip
  if (loading || (needsCatalog && catalogLoading)) {
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

  if (requireDownload && !isDownload && !isFastDownload) {
    return <Navigate to="/unauthorized" replace />
  }

  if (requireAdmin && !isAdmin) {
    return <Navigate to="/unauthorized" replace />
  }

  if (requireContribute && !canContribute) {
    return <Navigate to="/unauthorized" replace />
  }

  if (requireReleases && !canViewReleases) {
    return <Navigate to="/unauthorized" replace />
  }

  if (requireWip && !canViewWip) {
    return <Navigate to="/unauthorized" replace />
  }

  return children
}

export default ProtectedRoute

