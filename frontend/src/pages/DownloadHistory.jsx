import React, { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { getMediaUrl } from '../utils/constants'
import client from '../api/client'
import './DownloadHistory.css'

const DownloadHistory = () => {
  const [history, setHistory] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    loadHistory()
  }, [])

  const loadHistory = async () => {
    try {
      setLoading(true)
      setError(null)
      const response = await client.get('/api/download/history')
      setHistory(response.data.history || [])
    } catch (err) {
      console.error('Error loading download history:', err)
      setError('Failed to load download history')
    } finally {
      setLoading(false)
    }
  }

  const formatDate = (dateString) => {
    if (!dateString) return 'Unknown'
    const date = new Date(dateString)
    return date.toLocaleString()
  }

  const formatBytes = (bytes) => {
    if (!bytes) return '0 B'
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(2)} KB`
    if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(2)} MB`
    return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`
  }

  const getStatusBadgeClass = (status) => {
    switch (status) {
      case 'completed':
        return 'status-completed'
      case 'error':
        return 'status-error'
      case 'cancelled':
        return 'status-cancelled'
      default:
        return 'status-other'
    }
  }

  if (loading) {
    return <div className="download-history-container">
      <div className="loading">Loading download history...</div>
    </div>
  }

  if (error) {
    return <div className="download-history-container">
      <div className="error">{error}</div>
    </div>
  }

  return (
    <div className="download-history-container">
      <div className="download-history-header">
        <h1>Download History</h1>
        <p>View your completed, cancelled, and failed downloads</p>
      </div>

      {history.length === 0 ? (
        <div className="empty-state">
          <p>No download history found.</p>
          <Link to="/downloads" className="btn-primary">Go to Downloads</Link>
        </div>
      ) : (
        <div className="download-history-list">
          <table className="history-table">
            <thead>
              <tr>
                <th>Game</th>
                <th>System</th>
                <th>Version</th>
                <th>Status</th>
                <th>Size</th>
                <th>Downloaded</th>
                <th>Date</th>
              </tr>
            </thead>
            <tbody>
              {history.map((item) => (
                <tr key={item.id}>
                  <td className="game-cell">
                    {item.image && (
                      <img 
                        src={getMediaUrl(item.image)} 
                        alt={item.game_name}
                        className="game-thumbnail"
                        onError={(e) => {
                          e.target.style.display = 'none'
                        }}
                      />
                    )}
                    <div className="game-info">
                      <Link 
                        to={`/game/${item.system}/${encodeURIComponent(item.rompath)}`}
                        className="game-link"
                      >
                        {item.game_name}
                      </Link>
                    </div>
                  </td>
                  <td>{item.system_name || item.system}</td>
                  <td>
                    <span className="version-tag">{item.catalog_version || 'WIP'}</span>
                  </td>
                  <td>
                    <span className={`status-badge ${getStatusBadgeClass(item.status)}`}>
                      {item.status}
                    </span>
                  </td>
                  <td>
                    {item.file_size ? formatBytes(item.file_size) : 'Unknown'}
                  </td>
                  <td>
                    {item.bytes_transferred > 0 ? formatBytes(item.bytes_transferred) : '-'}
                  </td>
                  <td>{formatDate(item.timestamp)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

export default DownloadHistory

