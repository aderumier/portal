import { useState } from 'react'
import client from '../api/client'

export const useDownloadWithToken = () => {
  const [showTokenSelector, setShowTokenSelector] = useState(false)
  const [pendingGameId, setPendingGameId] = useState(null)

  const addToQueue = async (gameId, tokenName = null) => {
    try {
      // First, try to add without token_name (backend will handle single token or require selection)
      const response = await client.post('/api/download/queue', {
        game_id: gameId,
        token_name: tokenName
      })
      return { success: true, data: response.data }
    } catch (error) {
      // Check if backend requires token selection
      // Axios normalizes headers to lowercase, but check both cases
      const headers = error.response?.headers || {}
      const requiresSelection = 
        headers['x-requires-token-selection'] === 'true' ||
        headers['X-Requires-Token-Selection'] === 'true' ||
        error.response?.data?.detail?.includes('Multiple tokens found')
      
      if (error.response?.status === 400 && requiresSelection) {
        // User has multiple tokens, need to show selector
        // Don't throw error, just return and show selector
        setPendingGameId(gameId)
        setShowTokenSelector(true)
        return { success: false, requiresSelection: true }
      }
      // Other errors - throw to be handled by caller
      throw error
    }
  }

  const handleTokenSelected = async (selectedTokenName) => {
    if (!pendingGameId) return
    
    try {
      const response = await client.post('/api/download/queue', {
        game_id: pendingGameId,
        token_name: selectedTokenName
      })
      setShowTokenSelector(false)
      setPendingGameId(null)
      alert('Game added to download queue!')
      return { success: true, data: response.data }
    } catch (error) {
      const errorMsg = error.response?.data?.detail || 'Failed to add game to download queue. Please try again.'
      alert(errorMsg)
      throw error
    }
  }

  const cancelTokenSelection = () => {
    setShowTokenSelector(false)
    setPendingGameId(null)
  }

  return {
    addToQueue,
    handleTokenSelected,
    cancelTokenSelection,
    showTokenSelector,
    pendingGameId
  }
}

