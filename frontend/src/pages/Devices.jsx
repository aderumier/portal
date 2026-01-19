import React, { useState, useEffect } from 'react'
import client from '../api/client'
import './Devices.css'

const Devices = () => {
  const [devices, setDevices] = useState([])
  const [loadingDevices, setLoadingDevices] = useState(true)
  const [editingPorts, setEditingPorts] = useState({}) // {token_id: port_value}
  const [savingPorts, setSavingPorts] = useState({}) // {token_id: true/false}
  const [showAddDeviceModal, setShowAddDeviceModal] = useState(false)
  const [newDeviceName, setNewDeviceName] = useState('')
  const [generatingToken, setGeneratingToken] = useState(false)
  const [newTokenValue, setNewTokenValue] = useState(null)
  const [retestingPorts, setRetestingPorts] = useState({}) // {token_id: true/false}

  useEffect(() => {
    loadDevices()
    
    // Poll for updates every 10 seconds
    const interval = setInterval(() => {
      loadDevices()
    }, 10000)
    
    return () => clearInterval(interval)
  }, [])

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

  const handleRetestPort = async (tokenId) => {
    try {
      setRetestingPorts(prev => ({ ...prev, [tokenId]: true }))
      const response = await client.post(`/api/download/devices/${tokenId}/retest-port`)
      
      // Update the device in state with new port accessibility status
      setDevices(prev => prev.map(device => {
        if (device.token_id === tokenId && device.connection_info) {
          return {
            ...device,
            connection_info: {
              ...device.connection_info,
              p2p_port_accessible: response.data.p2p_port_accessible
            }
          }
        }
        return device
      }))
    } catch (error) {
      console.error('Error retesting port:', error)
      alert(error.response?.data?.detail || 'Failed to retest port')
    } finally {
      setRetestingPorts(prev => {
        const newState = { ...prev }
        delete newState[tokenId]
        return newState
      })
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

  return (
    <div className="devices-page">
      <div className="devices-header">
        <h1>Devices</h1>
        <button className="add-device-btn" onClick={handleAddDevice}>
          Add Device
        </button>
      </div>
      
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
                    {(device.custom_public_port || device.connection_info.external_port) && (
                      <span>
                        Public Port: {device.custom_public_port || device.connection_info.external_port}
                        {device.custom_public_port && (
                          <span className="custom-port-indicator"> (Custom)</span>
                        )}
                      </span>
                    )}
                    {device.connection_info.p2p_port_accessible !== undefined && (
                      <span className="port-status-row">
                        <span className={`port-status ${device.connection_info.p2p_port_accessible ? 'port-accessible' : 'port-not-accessible'}`}>
                          Port: {device.connection_info.p2p_port_accessible ? 'Available' : 'Not Available'}
                        </span>
                        <button
                          onClick={() => handleRetestPort(device.token_id)}
                          className="retest-port-btn"
                          disabled={retestingPorts[device.token_id]}
                          title="Retest port accessibility"
                        >
                          {retestingPorts[device.token_id] ? '...' : 'Retest'}
                        </button>
                      </span>
                    )}
                  </div>
                )}
                <div className="device-custom-port">
                  <label className="custom-port-label">Custom Public Port (disable upnp):</label>
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
                      Setting a custom port disables UPnP port mapping
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

export default Devices
