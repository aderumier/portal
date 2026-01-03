import React, { useState, useEffect } from 'react'
import { getMediaUrl } from '../utils/constants'
import client from '../api/client'
import './Downloads.css'

const Downloads = () => {
  const [queue, setQueue] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    loadQueue()
    
    // Poll for updates every 2 seconds
    const interval = setInterval(() => {
      loadQueue()
    }, 2000) // Poll every 2 seconds
    
    return () => clearInterval(interval)
  }, [])

  const loadQueue = async () => {
    try {
      setLoading(true)
      const response = await client.get('/api/download/queue')
      setQueue(response.data || [])
    } catch (error) {
      console.error('Error loading queue:', error)
    } finally {
      setLoading(false)
    }
  }

  const handleRemove = async (gameId) => {
    try {
      const encodedGameId = encodeURIComponent(encodeURIComponent(gameId))
      await client.delete(`/api/download/queue/${encodedGameId}`)
      await loadQueue()
    } catch (error) {
      console.error('Error removing game:', error)
      alert('Failed to remove game from queue')
    }
  }

  const handlePause = async (downloadId) => {
    try {
      await client.post(`/api/download/queue/${downloadId}/pause`)
      await loadQueue()
    } catch (error) {
      console.error('Error pausing download:', error)
      alert('Failed to pause download')
    }
  }

  const handleResume = async (downloadId) => {
    try {
      await client.post(`/api/download/queue/${downloadId}/resume`)
      await loadQueue()
    } catch (error) {
      console.error('Error resuming download:', error)
      alert('Failed to resume download')
    }
  }

  const handleClear = async () => {
    if (!confirm('Are you sure you want to clear your entire download queue?')) {
      return
    }

    try {
      await client.delete('/api/download/queue')
      await loadQueue()
    } catch (error) {
      console.error('Error clearing queue:', error)
      alert('Failed to clear queue')
    }
  }


  if (loading) {
    return <div className="loading">Loading downloads...</div>
  }

  return (
    <div className="downloads-page">
      <div className="downloads-header">
        <h1>My Downloads</h1>
        <div className="downloads-actions">
          <button className="clear-queue-btn" onClick={handleClear}>
            Clear Queue
          </button>
        </div>
      </div>

      {queue.length === 0 ? (
        <div className="no-downloads">No games in your download queue</div>
      ) : (
        <div className="downloads-table-container">
          <table className="downloads-table">
            <thead>
              <tr>
                <th>#</th>
                <th>Game</th>
                <th>System</th>
                <th>Token</th>
                <th>Status</th>
                <th>Progress</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {queue.map((item, index) => (
                <tr key={item.id}>
                  <td className="queue-number">{index + 1}</td>
                  <td className="game-info-cell">
                    {item.image && (
                      <img
                        className="table-game-image"
                        src={getMediaUrl(item.image)}
                        alt={item.game_name || 'Game'}
                        loading="lazy"
                      />
                    )}
                    <span className="game-name">{item.game_name || 'Unknown Game'}</span>
                  </td>
                  <td className="system-cell">
                    <span className="system-tag">{item.system_name || 'Unknown System'}</span>
                  </td>
                  <td className="token-cell">
                    <span className="token-tag">{item.token_name || '-'}</span>
                  </td>
                  <td className="status-cell">
                    <span className={`status-tag ${item.status}`}>
                      {item.status === 'user_queue' ? 'Queued' : 
                       item.status === 'pending' ? 'Pending' :
                       item.status === 'downloading' ? 'Downloading' :
                       item.status === 'paused' ? 'Paused' :
                       item.status === 'completed' ? 'Completed' :
                       item.status.charAt(0).toUpperCase() + item.status.slice(1)}
                    </span>
                  </td>
                  <td className="progress-cell">
                    {(item.status === 'downloading' || item.status === 'paused') && item.progress_percent !== undefined ? (
                      <div className="table-progress">
                        <div className="progress-bar">
                          <div 
                            className="progress-fill" 
                            style={{ width: `${item.progress_percent}%` }}
                          ></div>
                        </div>
                        <span className="progress-text">{item.progress_percent}%</span>
                      </div>
                    ) : (
                      <span className="no-progress">-</span>
                    )}
                  </td>
                  <td className="actions-cell">
                    <div className="action-buttons">
                      {item.status === 'pending' || item.status === 'downloading' ? (
                        <button
                          className="pause-download-btn"
                          onClick={() => handlePause(item.download_id || item.id)}
                          title="Pause download"
                        >
                          ⏸ Pause
                        </button>
                      ) : item.status === 'paused' ? (
                        <button
                          className="resume-download-btn"
                          onClick={() => handleResume(item.download_id || item.id)}
                          title="Resume download"
                        >
                          ▶ Resume
                        </button>
                      ) : null}
                      <button
                        className="remove-download-btn"
                        onClick={() => handleRemove(item.game_id)}
                        title="Remove from queue"
                      >
                        Remove
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

export default Downloads

