import React, { useState, useEffect } from 'react'
import { useAuth } from '../context/AuthContext'
import client from '../api/client'
import './UsersStats.css'

const UsersStats = () => {
  const { isAdmin } = useAuth()
  const [users, setUsers] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (isAdmin) {
      loadUsersStats()
    }
  }, [isAdmin])

  const loadUsersStats = async () => {
    try {
      setLoading(true)
      setError(null)
      const response = await client.get('/api/users/stats')
      setUsers(response.data.users || [])
    } catch (err) {
      console.error('Error loading users stats:', err)
      setError('Failed to load users statistics')
    } finally {
      setLoading(false)
    }
  }

  const formatDate = (dateStr) => {
    if (!dateStr) return 'Never'
    try {
      const date = new Date(dateStr)
      return date.toLocaleString()
    } catch (e) {
      return dateStr
    }
  }

  const formatMB = (mb) => {
    if (mb === 0) return '0 MB'
    if (mb < 1024) {
      return `${mb.toFixed(2)} MB`
    }
    return `${(mb / 1024).toFixed(2)} GB`
  }

  const formatTimeAgo = (dateStr) => {
    if (!dateStr) return 'Never'
    try {
      const date = new Date(dateStr)
      const now = new Date()
      const diffMs = now - date
      const diffSecs = Math.floor(diffMs / 1000)
      const diffMins = Math.floor(diffSecs / 60)
      const diffHours = Math.floor(diffMins / 60)
      const diffDays = Math.floor(diffHours / 24)

      if (diffDays > 0) {
        return `${diffDays} day${diffDays !== 1 ? 's' : ''} ago`
      } else if (diffHours > 0) {
        return `${diffHours} hour${diffHours !== 1 ? 's' : ''} ago`
      } else if (diffMins > 0) {
        return `${diffMins} minute${diffMins !== 1 ? 's' : ''} ago`
      } else {
        return 'Just now'
      }
    } catch (e) {
      return dateStr
    }
  }

  const getCountryFlag = (countryCode) => {
    if (!countryCode) return null
    // Convert country code (e.g., 'US', 'FR') to flag emoji
    // Each letter is converted to its regional indicator symbol
    const codePoints = countryCode
      .toUpperCase()
      .split('')
      .map(char => 127397 + char.charCodeAt())
    return String.fromCodePoint(...codePoints)
  }

  if (!isAdmin) {
    return (
      <div className="users-stats-page">
        <div className="users-stats-error">
          <p>You must have Admin role to access users statistics.</p>
        </div>
      </div>
    )
  }

  if (loading) {
    return (
      <div className="users-stats-page">
        <div className="users-stats-loading">Loading users statistics...</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="users-stats-page">
        <div className="users-stats-error">{error}</div>
      </div>
    )
  }

  return (
    <div className="users-stats-page">
      <h1>Users Statistics</h1>
      
      <div className="users-stats-summary">
        <div className="stat-card">
          <div className="stat-value">{users.length}</div>
          <div className="stat-label">Total Users</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{formatMB(users.reduce((sum, u) => sum + u.total_download_mb, 0))}</div>
          <div className="stat-label">Total Downloaded</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{users.reduce((sum, u) => sum + u.total_download_number, 0)}</div>
          <div className="stat-label">Total Games Downloaded</div>
        </div>
      </div>

      <div className="users-table-container">
        <table className="users-table">
          <thead>
            <tr>
              <th>Username</th>
              <th>User ID</th>
              <th>Total Downloaded</th>
              <th>Games Downloaded</th>
              <th>Medias Uploaded</th>
              <th>Medias Validated</th>
              <th>Last Login IP</th>
              <th>Country</th>
              <th>Last Login</th>
              <th>Account Created</th>
            </tr>
          </thead>
          <tbody>
            {users.length === 0 ? (
              <tr>
                <td colSpan="10" className="no-users">
                  No users found
                </td>
              </tr>
            ) : (
              users.map((user) => (
                <tr key={user.user_id}>
                  <td className="username-cell">
                    <span className="username">{user.username || user.user_id}</span>
                  </td>
                  <td className="userid-cell">
                    <span className="userid">{user.user_id}</span>
                  </td>
                  <td className="download-mb-cell">
                    <span className="download-mb">{formatMB(user.total_download_mb)}</span>
                  </td>
                  <td className="download-number-cell">
                    <span className="download-number">{user.total_download_number}</span>
                  </td>
                  <td className="medias-upload-cell">
                    <span className="medias-upload">{user.medias_upload || 0}</span>
                  </td>
                  <td className="medias-validated-cell">
                    <span className="medias-validated">{user.medias_validated || 0}</span>
                  </td>
                  <td className="last-login-ip-cell">
                    <span className="last-login-ip">{user.last_login_ip || '-'}</span>
                  </td>
                  <td className="country-cell">
                    {user.country ? (
                      <span className="country-flag" title={user.country}>
                        {getCountryFlag(user.country)}
                      </span>
                    ) : (
                      <span className="country-flag">-</span>
                    )}
                  </td>
                  <td className="last-login-cell">
                    <span className="last-login" title={formatDate(user.last_login)}>
                      {formatTimeAgo(user.last_login)}
                    </span>
                  </td>
                  <td className="created-at-cell">
                    <span className="created-at" title={formatDate(user.created_at)}>
                      {formatDate(user.created_at)}
                    </span>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default UsersStats

