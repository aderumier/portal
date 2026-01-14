import React, { useState, useEffect } from 'react'
import { useAuth } from '../context/AuthContext'
import client from '../api/client'
import './ClientsStats.css'

const ClientsStats = () => {
  const { isAdmin } = useAuth()
  const [tokens, setTokens] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (isAdmin) {
      loadTokensStats()
    }
  }, [isAdmin])

  const loadTokensStats = async () => {
    try {
      setLoading(true)
      setError(null)
      const response = await client.get('/api/users/tokens/stats')
      setTokens(response.data.tokens || [])
    } catch (err) {
      console.error('Error loading tokens stats:', err)
      setError('Failed to load clients statistics')
    } finally {
      setLoading(false)
    }
  }

  const formatMB = (mb) => {
    if (mb === 0) return '0 MB'
    if (mb < 1024) {
      return `${mb.toFixed(2)} MB`
    }
    return `${(mb / 1024).toFixed(2)} GB`
  }

  if (!isAdmin) {
    return (
      <div className="clients-stats-page">
        <div className="clients-stats-error">
          <p>You must have Admin role to access clients statistics.</p>
        </div>
      </div>
    )
  }

  if (loading) {
    return (
      <div className="clients-stats-page">
        <div className="clients-stats-loading">Loading clients statistics...</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="clients-stats-page">
        <div className="clients-stats-error">{error}</div>
      </div>
    )
  }

  return (
    <div className="clients-stats-page">
      <h1>Clients Statistics</h1>
      
      <div className="clients-stats-summary">
        <div className="stat-card">
          <div className="stat-value">{tokens.length}</div>
          <div className="stat-label">Total Tokens</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{formatMB(tokens.reduce((sum, t) => sum + (t.p2p_total_download_mb || 0), 0))}</div>
          <div className="stat-label">Total P2P Download</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{formatMB(tokens.reduce((sum, t) => sum + (t.p2p_total_upload_mb || 0), 0))}</div>
          <div className="stat-label">Total P2P Upload</div>
        </div>
      </div>

      <div className="clients-table-container">
        <table className="clients-table">
          <thead>
            <tr>
              <th>Token ID</th>
              <th>Token Name</th>
              <th>Username</th>
              <th>P2P Download</th>
              <th>P2P Upload</th>
            </tr>
          </thead>
          <tbody>
            {tokens.length === 0 ? (
              <tr>
                <td colSpan="5" className="no-tokens">
                  No tokens found
                </td>
              </tr>
            ) : (
              tokens.map((token) => (
                <tr key={token.token_id}>
                  <td className="token-id-cell">
                    <span className="token-id">{token.token_id}</span>
                  </td>
                  <td className="token-name-cell">
                    <span className="token-name">{token.token_name}</span>
                  </td>
                  <td className="username-cell">
                    <span className="username">{token.username || '-'}</span>
                  </td>
                  <td className="p2p-download-mb-cell">
                    <span className="p2p-download-mb">{formatMB(token.p2p_total_download_mb || 0)}</span>
                  </td>
                  <td className="p2p-upload-mb-cell">
                    <span className="p2p-upload-mb">{formatMB(token.p2p_total_upload_mb || 0)}</span>
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

export default ClientsStats

