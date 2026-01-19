import React, { useState, useEffect, useCallback } from 'react'
import { getMediaUrl } from '../utils/constants'
import client from '../api/client'
import './Downloads.css'

const Downloads = () => {
  const [queue, setQueue] = useState([])
  const [initialLoading, setInitialLoading] = useState(true)
  const [bandwidthLimit, setBandwidthLimit] = useState(null)
  const [maxBandwidthLimit, setMaxBandwidthLimit] = useState(null)
  const [bandwidthInput, setBandwidthInput] = useState('')
  const [savingBandwidth, setSavingBandwidth] = useState(false)
  const [devices, setDevices] = useState([])
  const [loadingDevices, setLoadingDevices] = useState(true)
  const [editingPorts, setEditingPorts] = useState({}) // {token_id: port_value}
  const [savingPorts, setSavingPorts] = useState({}) // {token_id: true/false}
  const [showAddDeviceModal, setShowAddDeviceModal] = useState(false)
  const [newDeviceName, setNewDeviceName] = useState('')
  const [generatingToken, setGeneratingToken] = useState(false)
  const [newTokenValue, setNewTokenValue] = useState(null)

  // Define formatMbits before it's used in useEffect
  const formatMbits = useCallback((bytes) => {
    if (!bytes) return '0'
    return (bytes / 125000).toFixed(2)
  }, [])

  useEffect(() => {
    loadQueue(true)
    loadBandwidthLimit()
    loadDevices()
    
    // Poll for updates every 10 seconds
    const interval = setInterval(() => {
      loadQueue(false) // Don't show loading on refresh
      loadDevices() // Also refresh devices status
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

  const loadDevices = async () => {
    try {
      setLoadingDevices(true)
      const response = await client.get('/api/download/devices')
      setDevices(response.data.devices || [])
    } catch (error) {
      console.error('Error loading devices:', error)
      setDevices([])
    } finally {
      setLoadingDevices(false)
    }
  }

  const formatDate = (dateString) => {
    if (!dateString) return 'Never'
    const date = new Date(dateString)
    return date.toLocaleString()
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

  const handlePortChange = (tokenId, value) => {
    setEditingPorts(prev => ({
      ...prev,
      [tokenId]: value === '' ? null : parseInt(value)
    }))
  }

  const handleSavePort = async (tokenId) => {
    const portValue = editingPorts[tokenId]
    
    // Validate port range
    if (portValue !== null && portValue !== undefined) {
      if (isNaN(portValue) || portValue < 1 || portValue > 65535) {
        alert('Port must be between 1 and 65535')
        return
      }
    }

    try {
      setSavingPorts(prev => ({ ...prev, [tokenId]: true }))
      await client.put(`/api/users/tokens/${tokenId}/custom-port`, {
        custom_public_port: portValue
      })
      
      // Clear editing state for this token
      setEditingPorts(prev => {
        const newState = { ...prev }
        delete newState[tokenId]
        return newState
      })
      
      // Reload devices to show updated port
      await loadDevices()
    } catch (error) {
      console.error('Error updating custom port:', error)
      alert(error.response?.data?.detail || 'Failed to update custom port')
    } finally {
      setSavingPorts(prev => {
        const newState = { ...prev }
        delete newState[tokenId]
        return newState
      })
    }
  }

  const handleClearPort = async (tokenId) => {
    try {
      setSavingPorts(prev => ({ ...prev, [tokenId]: true }))
      await client.put(`/api/users/tokens/${tokenId}/custom-port`, {
        custom_public_port: null
      })
      
      // Clear editing state for this token
      setEditingPorts(prev => {
        const newState = { ...prev }
        delete newState[tokenId]
        return newState
      })
      
      // Reload devices to show updated port
      await loadDevices()
    } catch (error) {
      console.error('Error clearing custom port:', error)
      alert(error.response?.data?.detail || 'Failed to clear custom port')
    } finally {
      setSavingPorts(prev => {
        const newState = { ...prev }
        delete newState[tokenId]
        return newState
      })
    }
  }

  const handleAddDevice = () => {
    setShowAddDeviceModal(true)
    setNewDeviceName('')
    setNewTokenValue(null)
  }

  const handleCloseModal = () => {
    setShowAddDeviceModal(false)
    setNewDeviceName('')
    setNewTokenValue(null)
  }

  const handleGenerateToken = async (e) => {
    e.preventDefault()
    if (!newDeviceName.trim()) {
      alert('Please enter a device name')
      return
    }

    try {
      setGeneratingToken(true)
      const response = await client.post('/api/users/tokens', {
        name: newDeviceName.trim()
      })
      setNewTokenValue(response.data.token)
      setNewDeviceName('')
      await loadDevices()
    } catch (error) {
      console.error('Error generating token:', error)
      alert(error.response?.data?.detail || 'Failed to generate token')
    } finally {
      setGeneratingToken(false)
    }
  }

  const handleDeleteToken = async (tokenId) => {
    if (!confirm('Are you sure you want to delete this device? This will permanently remove the token and cannot be undone.')) {
      return
    }

    try {
      await client.delete(`/api/users/tokens/${tokenId}`)
      await loadDevices()
      if (newTokenValue) {
        setNewTokenValue(null)
      }
    } catch (error) {
      console.error('Error deleting token:', error)
      alert(error.response?.data?.detail || 'Failed to delete device')
    }
  }

  const copyToClipboard = (text) => {
    navigator.clipboard.writeText(text).then(() => {
      alert('Token copied to clipboard!')
    }).catch(err => {
      console.error('Failed to copy:', err)
      alert('Failed to copy token to clipboard')
    })
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

      {/* Connected Devices Section */}
      <div className="connected-devices-section">
        <h2>Connected Devices</h2>
        <button className="add-device-btn" onClick={handleAddDevice}>
          Add Device
        </button>
        {loadingDevices ? (
          <div className="loading">Loading devices...</div>
        ) : devices.length === 0 ? (
          <div className="no-devices">No devices found</div>
        ) : (
          <div className="devices-list">
            {devices.map((device) => (
              <div key={device.token_id} className="device-item">
                <div className="device-info">
                  <div className="device-name">{device.token_name}</div>
                  <div className="device-status">
                    <span className={`status-indicator ${device.is_connected ? 'connected' : 'disconnected'}`}>
                      {device.is_connected ? '● Connected' : '○ Disconnected'}
                    </span>
                  </div>
                  {device.is_connected && device.connection_info && (
                    <div className="device-details">
                      <span>IP: {device.connection_info.ip}</span>
                      <span>Platform: {device.connection_info.platform}</span>
                      <span>Version: {device.connection_info.client_version}</span>
                      {device.connection_info.upnp_enabled !== undefined && (
                        <span>UPnP: {device.connection_info.upnp_enabled ? 'ON' : 'OFF'}</span>
                      )}
                      {device.connection_info.external_port && (
                        <span>
                          Public Port: {device.connection_info.external_port}
                          {device.custom_public_port && (
                            <span className="custom-port-indicator"> (Custom)</span>
                          )}
                        </span>
                      )}
                      {device.connection_info.p2p_port_accessible !== undefined && (
                        <span className={`port-status ${device.connection_info.p2p_port_accessible ? 'port-accessible' : 'port-not-accessible'}`}>
                          Port: {device.connection_info.p2p_port_accessible ? 'Available' : 'Not Available'}
                        </span>
                      )}
                    </div>
                  )}
                  <div className="device-custom-port">
                    <label className="custom-port-label">Custom Public Port:</label>
                    <div className="custom-port-controls">
                      <input
                        type="number"
                        min="1"
                        max="65535"
                        placeholder={device.custom_public_port ? device.custom_public_port.toString() : 'Not set'}
                        value={editingPorts[device.token_id] !== undefined ? (editingPorts[device.token_id] || '') : (device.custom_public_port || '')}
                        onChange={(e) => handlePortChange(device.token_id, e.target.value)}
                        className="custom-port-input"
                        disabled={savingPorts[device.token_id]}
                      />
                      <button
                        onClick={() => handleSavePort(device.token_id)}
                        className="save-port-btn"
                        disabled={savingPorts[device.token_id] || editingPorts[device.token_id] === undefined}
                        title="Save custom port"
                      >
                        {savingPorts[device.token_id] ? 'Saving...' : 'Save'}
                      </button>
                      {device.custom_public_port && (
                        <button
                          onClick={() => handleClearPort(device.token_id)}
                          className="clear-port-btn"
                          disabled={savingPorts[device.token_id]}
                          title="Clear custom port"
                        >
                          Clear
                        </button>
                      )}
                    </div>
                    {device.custom_public_port && (
                      <div className="custom-port-note">
                        Custom port will override UPnP port for P2P connections
                      </div>
                    )}
                  </div>
                  <div className="device-token">
                    <label>Token:</label>
                    <div className="token-display-wrapper">
                      <code>{device.token}</code>
                      <button 
                        className="copy-token-btn"
                        onClick={() => copyToClipboard(device.token)}
                        title="Copy token to clipboard"
                      >
                        Copy
                      </button>
                    </div>
                  </div>
                  <div className="device-meta">
                    <span>Created: {formatDate(device.created_at)}</span>
                    {device.last_used_at && (
                      <span>Last used: {formatDate(device.last_used_at)}</span>
                    )}
                  </div>
                  <button 
                    className="delete-device-btn"
                    onClick={() => handleDeleteToken(device.token_id)}
                  >
                    Delete Device
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Add Device Modal */}
      {showAddDeviceModal && (
        <div className="add-device-modal-overlay" onClick={handleCloseModal}>
          <div className="add-device-modal" onClick={(e) => e.stopPropagation()}>
            <h3>Add New Device</h3>
            <div className="token-warning">
              <p>
                <strong>⚠️ Important:</strong> Each token is bound to a single device/IP address. 
                Do not share your token with different machines or use it from multiple IP addresses 
                simultaneously, as it will be automatically blocked for security reasons.
              </p>
            </div>
            <form onSubmit={handleGenerateToken}>
              <input
                type="text"
                placeholder="Device Name (e.g., Batocera-home, ArcadeCabinet, Retrobat-Tv)"
                value={newDeviceName}
                onChange={(e) => setNewDeviceName(e.target.value)}
                className="device-name-input"
                disabled={generatingToken}
              />
              <button
                type="submit"
                disabled={generatingToken || !newDeviceName.trim()}
                className="generate-token-btn"
              >
                {generatingToken ? 'Generating...' : 'Generate Token'}
              </button>
            </form>
            {newTokenValue && (
              <div className="new-token-display">
                <p><strong>Token generated! Copy it now - you won't be able to see it again:</strong></p>
                <div className="token-display">
                  <code>{newTokenValue}</code>
                  <button
                    onClick={() => copyToClipboard(newTokenValue)}
                    className="copy-token-btn"
                  >
                    Copy
                  </button>
                </div>
              </div>
            )}
            <button onClick={handleCloseModal} className="close-modal-btn">
              Close
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

export default Downloads

