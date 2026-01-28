import React, { useState, useEffect, useCallback } from 'react'
import { getMediaUrl } from '../utils/constants'
import client from '../api/client'
import './Downloads.css'

const Downloads = () => {
  const [queue, setQueue] = useState([])
  const [uploads, setUploads] = useState([])
  const [initialLoading, setInitialLoading] = useState(true)
  const [bandwidthLimit, setBandwidthLimit] = useState(null)
  const [maxBandwidthLimit, setMaxBandwidthLimit] = useState(null)
  const [bandwidthInput, setBandwidthInput] = useState('')
  const [savingBandwidth, setSavingBandwidth] = useState(false)
  const [removingGameId, setRemovingGameId] = useState(null)

  // Define formatMbits before it's used in useEffect
  const formatMbits = useCallback((bytes) => {
    if (!bytes) return '0'
    return (bytes / 125000).toFixed(2)
  }, [])

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
      const limit = response.data.bandwidth_limit
      setBandwidthLimit(limit)
      setMaxBandwidthLimit(response.data.max_bandwidth_limit)
      // Set input value in Mbits/s
      setBandwidthInput(limit ? formatMbits(limit) : '')
    } catch (error) {
      console.error('Error loading bandwidth limit:', error)
    }
  }


  // Auto-save bandwidth limit with debouncing
  useEffect(() => {
    if (bandwidthInput === '' && bandwidthLimit === null) {
      // Initial state, don't save
      return
    }

    const timeoutId = setTimeout(async () => {
      // Convert input to bytes/s
      let limit = null
      if (bandwidthInput.trim() !== '') {
        const mbits = parseFloat(bandwidthInput)
        if (isNaN(mbits) || mbits < 0) {
          // Invalid input, reset to current value
          setBandwidthInput(bandwidthLimit ? formatMbits(bandwidthLimit) : '')
          return
        }
        // Check max limit
        if (maxBandwidthLimit && mbits > formatMbits(maxBandwidthLimit)) {
          // Exceeds max, reset to max
          setBandwidthInput(formatMbits(maxBandwidthLimit))
          limit = maxBandwidthLimit
        } else {
          // Convert Mbits/s to bytes/s
          limit = Math.round(mbits * 125000)
        }
      }

      // Only save if value changed
      if (limit !== bandwidthLimit) {
        try {
          setSavingBandwidth(true)
          await client.put('/api/users/bandwidth-limit', { bandwidth_limit: limit })
          setBandwidthLimit(limit)
        } catch (error) {
          console.error('Error updating bandwidth limit:', error)
          // Reset to current value on error
          setBandwidthInput(bandwidthLimit ? formatMbits(bandwidthLimit) : '')
          alert(error.response?.data?.detail || 'Failed to update bandwidth limit')
        } finally {
          setSavingBandwidth(false)
        }
      }
    }, 1000) // Debounce: wait 1 second after user stops typing

    return () => clearTimeout(timeoutId)
  }, [bandwidthInput, bandwidthLimit, maxBandwidthLimit, formatMbits])

  const loadQueue = async (isInitialLoad = false) => {
    try {
      if (isInitialLoad) {
        setInitialLoading(true)
      }
      // Load downloads and uploads from merged endpoint
      const response = await client.get('/api/download/queue')
      setQueue(response.data?.queue || [])
      setUploads(response.data?.uploads || [])
    } catch (error) {
      console.error('Error loading queue:', error)
    } finally {
      if (isInitialLoad) {
        setInitialLoading(false)
      }
    }
  }

  const handleRemove = async (gameId) => {
    if (removingGameId) return // Prevent multiple clicks
    setRemovingGameId(gameId)
    try {
      const encodedGameId = encodeURIComponent(encodeURIComponent(gameId))
      await client.delete(`/api/download/queue/${encodedGameId}`)
      await loadQueue()
    } catch (error) {
      console.error('Error removing game:', error)
      alert('Failed to remove game from queue')
    } finally {
      setRemovingGameId(null)
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
            <label className="bandwidth-label">
              Bandwidth Limit (Mbits/s):
            </label>
            <input
              type="number"
              className="bandwidth-input"
              placeholder={maxBandwidthLimit ? `Max: ${formatMbits(maxBandwidthLimit)} Mbits/s` : 'Mbits/s'}
              value={bandwidthInput}
              onChange={(e) => setBandwidthInput(e.target.value)}
              min="0"
              max={maxBandwidthLimit ? formatMbits(maxBandwidthLimit) : undefined}
              step="0.01"
              disabled={savingBandwidth}
            />
            {maxBandwidthLimit && (
              <span className="bandwidth-max">Max: {formatMbits(maxBandwidthLimit)} Mbits/s</span>
            )}
            {savingBandwidth && <span className="saving-indicator">Saving...</span>}
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
                <th>Version</th>
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
                  <td className="version-cell">
                    <span className="version-tag">{item.catalog_version || 'WIP'}</span>
                  </td>
                  <td className="token-cell">
                    <span className="token-tag">{item.token_name || '-'}</span>
                  </td>
                  <td className="status-cell">
                    <span className={`status-tag ${item.status}`}>
                      {item.status === 'user_queue' ? 'Queued' : 
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
                          {item.p2p_remote_token_name && (
                            <span className="progress-p2p-source" title={`P2P source: ${item.p2p_remote_token_name}`}>
                              P2P: {item.p2p_remote_token_name}
                            </span>
                          )}
                        </div>
                      </div>
                    ) : (
                      <span className="no-progress">-</span>
                    )}
                  </td>
                  <td className="actions-cell">
                    <div className="action-buttons">
                      {item.status === 'downloading' ? (
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
                        className={`remove-download-btn ${removingGameId === item.game_id ? 'removing' : ''}`}
                        onClick={() => handleRemove(item.game_id)}
                        title="Remove from queue"
                        disabled={removingGameId !== null}
                      >
                        {removingGameId === item.game_id ? 'Removing...' : 'Remove'}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Active P2P Uploads Section */}
      {uploads.length > 0 && (
        <div className="uploads-section">
          <h2 className="uploads-header">Active P2P Uploads</h2>
          <div className="downloads-table-container">
            <table className="downloads-table uploads-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Game</th>
                  <th>System</th>
                  <th>Version</th>
                  <th>Token</th>
                  <th>Uploading To</th>
                  <th>Progress</th>
                </tr>
              </thead>
              <tbody>
                {uploads.map((item, index) => (
                  <tr key={`upload-${item.id}`} className="upload-row">
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
                    <td className="version-cell">
                      <span className="version-tag">{item.catalog_version || 'WIP'}</span>
                    </td>
                    <td className="token-cell">
                      <span className="token-tag" title={`Source Token: ${item.source_token_name || 'Unknown'}`}>
                        {item.source_token_name || 'Unknown'}
                      </span>
                    </td>
                    <td className="target-cell">
                      <div className="upload-target-info">
                        <span className="target-token" title={`Token: ${item.target_token_name || 'Unknown'}`}>
                          {item.target_token_name || 'Unknown Device'}
                        </span>
                        {item.target_username && (
                          <span className="target-user">({item.target_username})</span>
                        )}
                      </div>
                    </td>
                    <td className="progress-cell">
                      <div className="table-progress">
                        <div className="progress-bar upload-progress-bar">
                          <div 
                            className="progress-fill upload-progress-fill" 
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
                            <span className="progress-bandwidth upload-bandwidth">{formatBytesPerSecond(item.bandwidth_used)}</span>
                          )}
                        </div>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

    </div>
  )
}

export default Downloads

