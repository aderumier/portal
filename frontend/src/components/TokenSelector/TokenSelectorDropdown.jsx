import React, { useState, useEffect, useRef } from 'react'
import client from '../../api/client'
import './TokenSelectorDropdown.css'

const TokenSelectorDropdown = ({ isOpen, onClose, onSelect, gameId }) => {
  const [tokens, setTokens] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const dropdownRef = useRef(null)

  useEffect(() => {
    if (isOpen) {
      loadTokens()
      // Close dropdown when clicking outside
      const handleClickOutside = (event) => {
        if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
          onClose()
        }
      }
      document.addEventListener('mousedown', handleClickOutside)
      return () => {
        document.removeEventListener('mousedown', handleClickOutside)
      }
    }
  }, [isOpen, onClose])

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
    <div className="token-selector-dropdown-overlay" onClick={onClose}>
      <div className="token-selector-dropdown" ref={dropdownRef} onClick={(e) => e.stopPropagation()}>
        <div className="token-selector-dropdown-header">
          <span>Select Token:</span>
          <button className="token-selector-dropdown-close" onClick={onClose}>×</button>
        </div>
        <div className="token-selector-dropdown-content">
          {loading ? (
            <div className="token-selector-dropdown-loading">Loading tokens...</div>
          ) : error ? (
            <div className="token-selector-dropdown-error">{error}</div>
          ) : (
            <select
              className="token-selector-select"
              onChange={(e) => {
                if (e.target.value) {
                  handleTokenSelect(e.target.value)
                }
              }}
              defaultValue=""
              autoFocus
            >
              <option value="" disabled>Choose a token...</option>
              {tokens.map((token) => (
                <option key={token.id} value={token.name}>
                  {token.name}
                </option>
              ))}
            </select>
          )}
        </div>
      </div>
    </div>
  )
}

export default TokenSelectorDropdown



