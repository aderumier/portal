import React, { useState, useEffect } from 'react'
import client from '../../api/client'
import './TokenSelector.css'

const TokenSelector = ({ isOpen, onClose, onSelect, gameId }) => {
  const [tokens, setTokens] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (isOpen) {
      loadTokens()
    }
  }, [isOpen])

  const loadTokens = async () => {
    try {
      setLoading(true)
      setError(null)
      const response = await client.get('/api/tokens')
      const activeTokens = response.data.tokens.filter(t => !t.revoked)
      setTokens(activeTokens)
    } catch (err) {
      console.error('Error loading tokens:', err)
      setError('Failed to load tokens')
    } finally {
      setLoading(false)
    }
  }

  const handleTokenSelect = (tokenName) => {
    onSelect(tokenName)
    onClose()
  }

  if (!isOpen) return null

  return (
    <div className="token-selector-overlay" onClick={onClose}>
      <div className="token-selector-modal" onClick={(e) => e.stopPropagation()}>
        <div className="token-selector-header">
          <h2>Select Token</h2>
          <button className="token-selector-close" onClick={onClose}>×</button>
        </div>
        <div className="token-selector-content">
          <p>You have multiple tokens. Please select which token to use for this download:</p>
          {loading ? (
            <div className="token-selector-loading">Loading tokens...</div>
          ) : error ? (
            <div className="token-selector-error">{error}</div>
          ) : (
            <div className="token-selector-list">
              {tokens.map((token) => (
                <button
                  key={token.id}
                  className="token-selector-item"
                  onClick={() => handleTokenSelect(token.name)}
                >
                  <div className="token-selector-item-name">{token.name}</div>
                  {token.last_used_at && (
                    <div className="token-selector-item-meta">
                      Last used: {new Date(token.last_used_at).toLocaleDateString()}
                    </div>
                  )}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default TokenSelector




