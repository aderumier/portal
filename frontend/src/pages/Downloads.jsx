import React, { useState, useEffect } from 'react'
import { getMediaUrl } from '../utils/constants'
import client from '../api/client'
import './Downloads.css'

const Downloads = () => {
  const [queue, setQueue] = useState([])
  const [initialLoading, setInitialLoading] = useState(true)
  const [bandwidthLimit, setBandwidthLimit] = useState(null)
  const [maxBandwidthLimit, setMaxBandwidthLimit] = useState(null)
  const [editingBandwidth, setEditingBandwidth] = useState(false)
  const [bandwidthInput, setBandwidthInput] = useState('')

  useEffect(() => {
    loadQueue(true)
    loadBandwidthLimit()
    
    // Poll for updates every 10 seconds
    const interval = setInterval(() => {
      loadQueue(false) // Don't show loading on refresh
    }, 10000) // Poll every 10 seconds
    
    return () => clearInterval(interval)
  }, [])

  const loadBandwidthLimit = async () => {
    try {
      const response = await client.get('/api/users/bandwidth-limit')
      setBandwidthLimit(response.data.bandwidth_limit)
      setMaxBandwidthLimit(response.data.max_bandwidth_limit)
    } catch (error) {
      console.error('Error loading bandwidth limit:', error)
    }
  }

  const handleBandwidthSave = async () => {
    try {
      let limit = null
      if (bandwidthInput !== '') {
        const mbits = parseFloat(bandwidthInput)
        if (isNaN(mbits) || mbits < 0) {
          alert('Invalid bandwidth value')
          return
        }
        // Convert Mbits/s to bytes/s
        limit = Math.round(mbits * 125000)
      }
      await client.put('/api/users/bandwidth-limit', { bandwidth_limit: limit })
      setBandwidthLimit(limit)
      setEditingBandwidth(false)
      setBandwidthInput('')
      alert('Bandwidth limit updated successfully')
    } catch (error) {
      console.error('Error updating bandwidth limit:', error)
      alert(error.response?.data?.detail || 'Failed to update bandwidth limit')
    }
  }

  const handleBandwidthCancel = () => {
    setEditingBandwidth(false)
    setBandwidthInput('')
  }

  const formatMbits = (bytes) => {
    if (!bytes) return '0'
    return (bytes / 125000).toFixed(2)
  }

  const loadQueue = async (isInitialLoad = false) => {
    try {
      if (isInitialLoad) {
        setInitialLoading(true)
      }
      const response = await client.get('/api/download/queue')
      setQueue(response.data || [])
    } catch (error) {
      console.error('Error loading queue:', error)
    } finally {
      if (isInitialLoad) {
        setInitialLoading(false)
      }
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

  const formatBytes = (bytes) => {
    if (!bytes || bytes === 0) return '0 B'
    const k = 1024
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB']
    const i = Math.floor(Math.log(bytes) / Math.log(k))
    return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i]
  }

  const formatBytesPerSecond = (bytesPerSecond) => {
    if (!bytesPerSecond || bytesPerSecond === 0) return '0 Mbits/s'
    // Convert bytes/s to Mbits/s (1 Mbit = 125,000 bytes)
    const mbitsPerSecond = bytesPerSecond / 125000
    return `${mbitsPerSecond.toFixed(2)} Mbits/s`
  }


  if (initialLoading) {
    return <div className="loading">Loading downloads...</div>
  }

  return (
    <div className="downloads-page">
      <div className="downloads-header">
        <h1>My Downloads</h1>
        <div className="downloads-actions">
          <div className="bandwidth-limit-section">
            {!editingBandwidth ? (
              <>
                <span className="bandwidth-label">
                  Bandwidth Limit: {bandwidthLimit ? `${formatMbits(bandwidthLimit)} Mbits/s` : 'Not set'}
                  {maxBandwidthLimit && ` (Max: ${formatMbits(maxBandwidthLimit)} Mbits/s)`}
                </span>
                <button className="edit-bandwidth-btn" onClick={() => {
                  setEditingBandwidth(true)
                  setBandwidthInput(bandwidthLimit ? formatMbits(bandwidthLimit) : '')
                }}>
                  Edit
                </button>
              </>
            ) : (
              <>
                <input
                  type="number"
                  className="bandwidth-input"
                  placeholder={maxBandwidthLimit ? `Max: ${formatMbits(maxBandwidthLimit)} Mbits/s` : 'Mbits/s'}
                  value={bandwidthInput}
                  onChange={(e) => setBandwidthInput(e.target.value)}
                  min="0"
                  max={maxBandwidthLimit ? formatMbits(maxBandwidthLimit) : undefined}
                  step="0.01"
                />
                <button className="save-bandwidth-btn" onClick={handleBandwidthSave}>
                  Save
                </button>
                <button className="cancel-bandwidth-btn" onClick={handleBandwidthCancel}>
                  Cancel
                </button>
              </>
            )}
          </div>
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
                    {(item.status === 'downloading' || item.status === 'paused') && (item.progress_percent !== undefined || item.file_size) ? (
                      <div className="table-progress">
                        <div className="progress-bar">
                          <div 
                            className="progress-fill" 
                            style={{ width: `${item.progress_percent || 0}%` }}
                          ></div>
                        </div>
                        <div className="progress-info">
                          {item.progress_percent !== undefined && (
                            <span className="progress-text">{item.progress_percent}%</span>
                          )}
                          {item.file_size && (
                            <span className="progress-size">
                              {formatBytes(item.bytes_transferred || 0)} / {formatBytes(item.file_size)}
                            </span>
                          )}
                          {item.bandwidth_used > 0 && (
                            <span className="progress-bandwidth">{formatBytesPerSecond(item.bandwidth_used)}</span>
                          )}
                        </div>
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

