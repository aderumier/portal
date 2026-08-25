import React, { useState, useEffect } from 'react'
import { useAuth } from '../context/AuthContext'
import client from '../api/client'
import {
  useTableSortFilter, SortIcon, ColumnFilter,
  cmpText, cmpNum, cmpAuto, cmpDate, cmpIp,
} from '../utils/tableSort'
import './ConnectedClients.css'

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

// Same precedence the Port cell renders with.
const portOf = (c) => c.custom_public_port || c.upnp_port || 8765
const upnpRank = (c) => (c.custom_public_port ? 0 : c.upnp_enabled ? 2 : 1)
const upnpLabel = (c) => (c.custom_public_port ? 'disabled' : c.upnp_enabled ? 'ON' : 'OFF')
const openRank = (c) => (c.p2p_port_accessible === true ? 2 : c.p2p_port_accessible === false ? 1 : 0)
const openLabel = (c) => (c.p2p_port_accessible === true ? 'YES' : c.p2p_port_accessible === false ? 'NO' : 'N/A')

// filterValue returns the text shown in the cell, so a search matches what the
// admin actually reads on screen.
const COLUMNS = [
  { key: 'username',           label: 'Username',           sortFn: (a, b) => cmpText(a.username, b.username),                             filterValue: c => c.username || 'N/A' },
  { key: 'token_name',         label: 'Token Name',         sortFn: (a, b) => cmpText(a.token_name, b.token_name),                         filterValue: c => c.token_name || 'N/A' },
  { key: 'ip',                 label: 'IP Address',         sortFn: (a, b) => cmpIp(a.ip, b.ip),                                           filterValue: c => c.ip || 'Unknown' },
  { key: 'platform',           label: 'Platform',           sortFn: (a, b) => cmpText(a.platform, b.platform),                             filterValue: c => c.platform || 'Unknown' },
  { key: 'client_version',     label: 'Client Version',     sortFn: (a, b) => cmpAuto(a.client_version, b.client_version),                 filterValue: c => c.client_version || 'Unknown' },
  { key: 'upnp',               label: 'UPnP',               sortFn: (a, b) => upnpRank(a) - upnpRank(b),                                   filterValue: upnpLabel },
  { key: 'local_ip',           label: 'Local IP',           sortFn: (a, b) => cmpIp(a.local_ip, b.local_ip),                               filterValue: c => c.local_ip || 'N/A' },
  { key: 'port',               label: 'Port',               sortFn: (a, b) => portOf(a) - portOf(b),                                       filterValue: c => `${portOf(c)}${c.custom_public_port ? ' (Custom)' : ''}` },
  { key: 'open',               label: 'OPEN',               sortFn: (a, b) => openRank(a) - openRank(b),                                   filterValue: openLabel },
  { key: 'upload_bandwidth',   label: 'Upload Bandwidth',   sortFn: (a, b) => cmpNum(a.upload_bandwidth, b.upload_bandwidth),              filterValue: c => formatBandwidth(c.upload_bandwidth) },
  { key: 'download_bandwidth', label: 'Download Bandwidth', sortFn: (a, b) => cmpNum(a.download_bandwidth, b.download_bandwidth),          filterValue: c => formatBandwidth(c.download_bandwidth) },
  { key: 'connected_at',       label: 'Connected At',       sortFn: (a, b) => cmpDate(a.connected_at, b.connected_at),                     filterValue: c => formatDate(c.connected_at) },
  { key: 'token_id',           label: 'Token ID',           sortFn: (a, b) => cmpAuto(a.token_id, b.token_id),                             filterValue: c => c.token_id || 'N/A' },
  { key: 'action',             label: 'Action',             sortFn: null,                                                                  filterValue: null },
]

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

  const {
    sortKey, sortDir, handleSort,
    filters, setFilter, clearFilters, activeFilterCount,
    displayedRows,
  } = useTableSortFilter(connections, COLUMNS)

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
        <p>
          Total connected: {connections.length}
          {activeFilterCount > 0 && ` — ${displayedRows.length} matching`}
        </p>
        {activeFilterCount > 0 && (
          <button className="clear-filters-btn" onClick={clearFilters}>Clear filters</button>
        )}
      </div>

      {connections.length === 0 ? (
        <div className="no-clients">
          <p>No clients currently connected</p>
        </div>
      ) : (
        <div className="clients-grid">
          <div className="clients-grid-header">
            {COLUMNS.map(col => (
              <div
                key={col.key}
                className={`grid-cell${col.sortFn ? ' sortable' : ''}`}
                onClick={() => handleSort(col.key)}
              >
                {col.label}<SortIcon col={col} sortKey={sortKey} sortDir={sortDir} />
              </div>
            ))}
          </div>
          <div className="clients-grid-filters">
            {COLUMNS.map(col => (
              <div key={col.key} className="grid-cell">
                <ColumnFilter col={col} filters={filters} setFilter={setFilter} />
              </div>
            ))}
          </div>
          {displayedRows.length === 0 && (
            <div className="no-clients-match">No clients match the current filters</div>
          )}
          {displayedRows.map((conn, index) => (
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
                {conn.local_ip ? (
                  <span title="LAN address the gateway forwards to">{conn.local_ip}</span>
                ) : (
                  <span style={{ color: '#999' }} title="No port mapping, or client too old to report it">N/A</span>
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

