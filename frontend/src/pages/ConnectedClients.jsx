import React, { useState, useEffect } from 'react'
import { useAuth } from '../context/AuthContext'
import client from '../api/client'
import './ConnectedClients.css'

const ConnectedClients = () => {
  const { isAdmin } = useAuth()
  const [connections, setConnections] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [logModalOpen, setLogModalOpen] = useState(false)
  const [logContent, setLogContent] = useState('')
  const [logLoading, setLogLoading] = useState(false)
  const [logTokenId, setLogTokenId] = useState(null)
  const [logTokenName, setLogTokenName] = useState('')

  useEffect(() => {
    if (isAdmin) {
      loadConnections()
      // Refresh every 5 seconds
      const interval = setInterval(loadConnections, 5000)
      return () => clearInterval(interval)
    }
  }, [isAdmin])

  const loadConnections = async () => {
    try {
      setError(null)
      const response = await client.get('/api/download/clients/connected')
      setConnections(response.data.connections || [])
    } catch (err) {
      console.error('Error loading connected clients:', err)
      setError('Failed to load connected clients')
    } finally {
      setLoading(false)
    }
  }

  const formatDate = (dateString) => {
    if (!dateString) return 'Unknown'
    try {
      const date = new Date(dateString)
      return date.toLocaleString()
    } catch (e) {
      return dateString
    }
  }

  const formatBandwidth = (mbps) => {
    if (mbps === null || mbps === undefined) return 'N/A'
    return `${mbps.toFixed(2)} Mbits/s`
  }

  const handleViewLogs = async (tokenId, tokenName) => {
    try {
      setLogLoading(true)
      setLogTokenId(tokenId)
      setLogTokenName(tokenName || `Token ${tokenId}`)
      setLogModalOpen(true)
      
      const response = await client.get(`/api/download/clients/${tokenId}/logs`)
      setLogContent(response.data.logs || response.data.message || 'No logs available')
    } catch (err) {
      console.error('Error loading client logs:', err)
      setLogContent(`Error loading logs: ${err.response?.data?.detail || err.message || 'Unknown error'}`)
    } finally {
      setLogLoading(false)
    }
  }

  const handleCloseLogModal = () => {
    setLogModalOpen(false)
    setLogContent('')
    setLogTokenId(null)
    setLogTokenName('')
  }

  if (loading) {
    return (
      <div className="connected-clients">
        <h1>Connected Clients</h1>
        <p>Loading...</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="connected-clients">
        <h1>Connected Clients</h1>
        <div className="error">{error}</div>
      </div>
    )
  }

  return (
    <div className="connected-clients">
      <h1>Connected Clients</h1>
      <div className="clients-header">
        <p>Total connected: {connections.length}</p>
      </div>
      
      {connections.length === 0 ? (
        <div className="no-clients">
          <p>No clients currently connected</p>
        </div>
      ) : (
        <div className="clients-grid">
          <div className="clients-grid-header">
            <div className="grid-cell">Username</div>
            <div className="grid-cell">Token Name</div>
            <div className="grid-cell">IP Address</div>
            <div className="grid-cell">Platform</div>
            <div className="grid-cell">Client Version</div>
            <div className="grid-cell">UPnP</div>
            <div className="grid-cell">Port</div>
            <div className="grid-cell">OPEN</div>
            <div className="grid-cell">Upload Bandwidth</div>
            <div className="grid-cell">Download Bandwidth</div>
            <div className="grid-cell">Connected At</div>
            <div className="grid-cell">Token ID</div>
            <div className="grid-cell">Action</div>
          </div>
          {connections.map((conn, index) => (
            <div key={conn.token_id || index} className="clients-grid-row">
              <div className="grid-cell">{conn.username || 'N/A'}</div>
              <div className="grid-cell">{conn.token_name || 'N/A'}</div>
              <div className="grid-cell">{conn.ip || 'Unknown'}</div>
              <div className="grid-cell">{conn.platform || 'Unknown'}</div>
              <div className="grid-cell">{conn.client_version || 'Unknown'}</div>
              <div className="grid-cell">
                {conn.custom_public_port ? (
                  <span title="UPnP disabled (custom public port configured)">disabled</span>
                ) : conn.upnp_enabled ? (
                  <span title="UPnP enabled">ON</span>
                ) : (
                  <span title="UPnP disabled">OFF</span>
                )}
              </div>
              <div className="grid-cell">
                {(() => {
                  // Priority: custom_public_port > upnp_port > default 8765
                  const port = conn.custom_public_port || conn.upnp_port || 8765
                  return (
                    <>
                      {port}
                      {conn.custom_public_port && (
                        <span style={{ color: '#5865f2', marginLeft: '4px' }} title="Custom public port">(Custom)</span>
                      )}
                    </>
                  )
                })()}
              </div>
              <div className="grid-cell">
                {conn.p2p_port_accessible === true ? (
                  <span style={{ color: '#4caf50' }}>YES</span>
                ) : conn.p2p_port_accessible === false ? (
                  <span style={{ color: '#f44336' }}>NO</span>
                ) : (
                  <span style={{ color: '#999' }}>N/A</span>
                )}
              </div>
              <div className="grid-cell">{formatBandwidth(conn.upload_bandwidth)}</div>
              <div className="grid-cell">{formatBandwidth(conn.download_bandwidth)}</div>
              <div className="grid-cell">{formatDate(conn.connected_at)}</div>
              <div className="grid-cell">{conn.token_id || 'N/A'}</div>
              <div className="grid-cell">
                <button
                  className="view-logs-btn"
                  onClick={() => handleViewLogs(conn.token_id, conn.token_name)}
                  title="View client logs"
                >
                  📋
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {logModalOpen && (
        <div className="log-modal-overlay" onClick={handleCloseLogModal}>
          <div className="log-modal" onClick={(e) => e.stopPropagation()}>
            <div className="log-modal-header">
              <h2>Client Logs - {logTokenName}</h2>
              <button className="log-modal-close" onClick={handleCloseLogModal}>×</button>
            </div>
            <div className="log-modal-content">
              {logLoading ? (
                <div className="log-loading">Loading logs...</div>
              ) : (
                <pre className="log-content">{logContent}</pre>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default ConnectedClients

