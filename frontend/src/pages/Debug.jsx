import React, { useState, useEffect } from 'react'
import { useAuth } from '../context/AuthContext'
import client from '../api/client'
import './Account.css'

const Debug = () => {
  const { isAdmin } = useAuth()
  const [forcedTargets, setForcedTargets] = useState({})
  const [sourceTokenId, setSourceTokenId] = useState('')
  const [targetTokenId, setTargetTokenId] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)
  const [success, setSuccess] = useState(null)

  useEffect(() => {
    if (isAdmin) {
      loadForcedTargets()
    }
  }, [isAdmin])

  const loadForcedTargets = async () => {
    try {
      setLoading(true)
      setError(null)
      const response = await client.get('/api/debug/p2p-forced-targets')
      setForcedTargets(response.data.forced_targets || {})
    } catch (err) {
      console.error('Error loading forced targets:', err)
      setError('Failed to load forced targets')
    } finally {
      setLoading(false)
    }
  }

  const handleSave = async (e) => {
    e.preventDefault()
    
    if (!sourceTokenId || !targetTokenId) {
      setError('Please provide both source and target token IDs')
      return
    }

    const sourceId = parseInt(sourceTokenId)
    const targetId = parseInt(targetTokenId)

    if (isNaN(sourceId) || isNaN(targetId)) {
      setError('Token IDs must be valid numbers')
      return
    }

    try {
      setSaving(true)
      setError(null)
      setSuccess(null)
      
      await client.post('/api/debug/p2p-forced-targets', {
        source_token_id: sourceId,
        target_token_id: targetId
      })

      setSuccess('Forced target saved successfully')
      setSourceTokenId('')
      setTargetTokenId('')
      await loadForcedTargets()
    } catch (err) {
      console.error('Error saving forced target:', err)
      setError(err.response?.data?.detail || 'Failed to save forced target')
    } finally {
      setSaving(false)
    }
  }

  const handleRemove = async (sourceTokenId) => {
    try {
      setError(null)
      setSuccess(null)
      
      await client.delete(`/api/debug/p2p-forced-targets/${sourceTokenId}`)
      
      setSuccess('Forced target removed successfully')
      await loadForcedTargets()
    } catch (err) {
      console.error('Error removing forced target:', err)
      setError(err.response?.data?.detail || 'Failed to remove forced target')
    }
  }

  if (loading) {
    return (
      <div className="account-page">
        <div className="loading">Loading...</div>
      </div>
    )
  }

  return (
    <div className="account-page">
      <h1>Debug</h1>

      <div className="account-section">
        <h2>P2P Forced Target Selection</h2>
        <p className="section-description">
          Force a specific target token_id for P2P peer selection for a specific source token_id.
          This will override the normal peer selection algorithm.
        </p>

        {error && (
          <div className="token-warning" style={{ backgroundColor: 'rgba(220, 53, 69, 0.15)', borderColor: '#dc3545', color: '#721c24' }}>
            <p>{error}</p>
          </div>
        )}

        {success && (
          <div className="token-warning" style={{ backgroundColor: 'rgba(40, 167, 69, 0.15)', borderColor: '#28a745', color: '#155724' }}>
            <p>{success}</p>
          </div>
        )}

        <form onSubmit={handleSave} className="token-form">
          <input
            type="number"
            className="token-input"
            placeholder="Source Token ID"
            value={sourceTokenId}
            onChange={(e) => setSourceTokenId(e.target.value)}
            required
          />
          <input
            type="number"
            className="token-input"
            placeholder="Target Token ID"
            value={targetTokenId}
            onChange={(e) => setTargetTokenId(e.target.value)}
            required
          />
          <button
            type="submit"
            className="generate-btn"
            disabled={saving}
          >
            {saving ? 'Saving...' : 'Save'}
          </button>
        </form>

        <div className="tokens-list">
          <h3>Current Forced Targets</h3>
          {Object.keys(forcedTargets).length === 0 ? (
            <div className="no-tokens">No forced targets configured</div>
          ) : (
            <table className="tokens-table">
              <thead>
                <tr>
                  <th>Source Token ID</th>
                  <th>Target Token ID</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(forcedTargets).map(([source, target]) => (
                  <tr key={source}>
                    <td>{source}</td>
                    <td>{target}</td>
                    <td>
                      <button
                        className="revoke-btn"
                        onClick={() => handleRemove(source)}
                      >
                        Remove
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  )
}

export default Debug
