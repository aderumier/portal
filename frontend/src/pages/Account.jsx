import React, { useState, useEffect } from 'react'
import { useAuth } from '../context/AuthContext'
import client from '../api/client'
import './Account.css'

const Account = () => {
  const { user, isDownload, isFastDownload } = useAuth()
  const [tokens, setTokens] = useState([])
  const [loading, setLoading] = useState(true)
  const [newTokenName, setNewTokenName] = useState('')
  const [generating, setGenerating] = useState(false)
  const [newToken, setNewToken] = useState(null)
  
  // Check if user has download or fastdownload role
  const hasDownloadAccess = isDownload || isFastDownload

  useEffect(() => {
    loadTokens()
  }, [])

  const loadTokens = async () => {
    try {
      setLoading(true)
      const response = await client.get('/api/users/tokens')
      setTokens(response.data.tokens || [])
    } catch (error) {
      console.error('Error loading tokens:', error)
    } finally {
      setLoading(false)
    }
  }

  const handleGenerate = async (e) => {
    e.preventDefault()
    if (!newTokenName.trim()) {
      alert('Please enter a token name')
      return
    }

    try {
      setGenerating(true)
      const response = await client.post('/api/users/tokens', {
        name: newTokenName
      })
      setNewToken(response.data.token)
      setNewTokenName('')
      await loadTokens()
    } catch (error) {
      console.error('Error generating token:', error)
      alert('Failed to generate token')
    } finally {
      setGenerating(false)
    }
  }

  const handleRevoke = async (tokenId) => {
    if (!confirm('Are you sure you want to revoke this token?')) {
      return
    }

    try {
      await client.delete(`/api/users/tokens/${tokenId}`)
      await loadTokens()
      if (newToken) {
        setNewToken(null)
      }
    } catch (error) {
      console.error('Error revoking token:', error)
      alert('Failed to revoke token')
    }
  }

  if (loading) {
    return <div className="loading">Loading account...</div>
  }

  return (
    <div className="account-page">
      <h1>Account Settings</h1>

      <div className="account-section">
        <h2>User Information</h2>
        <div className="user-info">
          <p><strong>Username:</strong> {user?.username}</p>
          <p><strong>User ID:</strong> {user?.id}</p>
          <p><strong>Guild Member:</strong> {user?.is_guild_member ? 'Yes' : 'No'}</p>
          <p><strong>Download Role:</strong> {user?.download_role_name || user?.fastdownload_role_name || 'No'}</p>
          {user?.fastdownload_role_name && (
            <p><strong>Fast Download Role:</strong> {user?.fastdownload_role_name}</p>
          )}
          <p><strong>Admin Role:</strong> {user?.admin_role_name || 'No'}</p>
        </div>
      </div>

      {hasDownloadAccess && (
        <div className="account-section">
          <h2>API Tokens</h2>
          <p className="section-description">
            Generate API tokens to authenticate with the download service.
          </p>

          <div className="token-warning">
            <p>
              <strong>⚠️ Important:</strong> Each token is bound to a single device/IP address. 
              Do not share your token with different machines or use it from multiple IP addresses 
              simultaneously, as it will be automatically blocked for security reasons.
            </p>
          </div>

          {newToken && (
            <div className="new-token-alert">
              <p><strong>New token generated! Copy it now - you won't be able to see it again:</strong></p>
              <div className="token-display">
                <code>{newToken}</code>
                <button
                  onClick={() => {
                    navigator.clipboard.writeText(newToken)
                    alert('Token copied to clipboard!')
                  }}
                >
                  Copy
                </button>
              </div>
              <button
                className="dismiss-btn"
                onClick={() => setNewToken(null)}
              >
                Dismiss
              </button>
            </div>
          )}

          <form onSubmit={handleGenerate} className="token-form">
            <input
              type="text"
              placeholder="Device Name (E.G., Batocera-home, ArcadeCabinet,Retrobat-Tv, ...)"
              value={newTokenName}
              onChange={(e) => setNewTokenName(e.target.value)}
              className="token-input"
            />
            <button
              type="submit"
              disabled={generating || !newTokenName.trim()}
              className="generate-btn"
            >
              {generating ? 'Generating...' : 'Generate Token'}
            </button>
          </form>

          <div className="tokens-list">
            <h3>Your Tokens</h3>
            {tokens.length === 0 ? (
              <p className="no-tokens">No tokens generated yet</p>
            ) : (
              <table className="tokens-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Token Preview</th>
                    <th>Created</th>
                    <th>Last Used</th>
                    <th>Status</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {tokens.map((token) => (
                    <tr key={token.id}>
                      <td>{token.name}</td>
                      <td>
                        <code>{token.token_preview}</code>
                      </td>
                      <td>
                        {token.created_at
                          ? new Date(token.created_at).toLocaleDateString()
                          : 'N/A'}
                      </td>
                      <td>
                        {token.last_used_at
                          ? new Date(token.last_used_at).toLocaleDateString()
                          : 'Never'}
                      </td>
                      <td>
                        <span className={`status-badge ${token.revoked ? 'revoked' : 'active'}`}>
                          {token.revoked ? 'Revoked' : 'Active'}
                        </span>
                      </td>
                      <td>
                        {!token.revoked && (
                          <button
                            className="revoke-btn"
                            onClick={() => handleRevoke(token.id)}
                          >
                            Revoke
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

export default Account

