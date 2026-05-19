import React, { useState, useEffect, useRef, useCallback } from 'react'
import { Link } from 'react-router-dom'
import client from '../api/client'
import './DownloadHistory.css'

const PAGE_SIZE = 100

const GlobalDownloadHistory = () => {
  const [history, setHistory] = useState([])
  const [loading, setLoading] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [hasMore, setHasMore] = useState(true)
  const [error, setError] = useState(null)
  const [selectedLog, setSelectedLog] = useState(null)
  const [logContent, setLogContent] = useState(null)
  const [loadingLog, setLoadingLog] = useState(false)

  const sentinelRef = useRef(null)
  const offsetRef = useRef(0)

  const loadPage = useCallback(async (offset, append) => {
    try {
      if (offset === 0) setLoading(true)
      else setLoadingMore(true)
      setError(null)
      const response = await client.get('/api/download/history/all', {
        params: { limit: PAGE_SIZE, offset }
      })
      const items = response.data.history || []
      if (append) {
        setHistory(prev => [...prev, ...items])
      } else {
        setHistory(items)
      }
      setHasMore(items.length === PAGE_SIZE)
      offsetRef.current = offset + items.length
    } catch (err) {
      console.error('Error loading global download history:', err)
      setError('Failed to load download history')
    } finally {
      setLoading(false)
      setLoadingMore(false)
    }
  }, [])

  useEffect(() => {
    loadPage(0, false)
  }, [loadPage])

  useEffect(() => {
    if (!sentinelRef.current) return
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && hasMore && !loadingMore && !loading) {
          loadPage(offsetRef.current, true)
        }
      },
      { threshold: 0.1 }
    )
    observer.observe(sentinelRef.current)
    return () => observer.disconnect()
  }, [hasMore, loadingMore, loading, loadPage])

  const formatDate = (dateString) => {
    if (!dateString) return 'Unknown'
    return new Date(dateString).toLocaleString()
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
      case 'completed': return 'status-completed'
      case 'error': return 'status-error'
      case 'cancelled': return 'status-cancelled'
      default: return 'status-other'
    }
  }

  const fetchLog = async (downloadId) => {
    try {
      setLoadingLog(true)
      setError(null)
      const response = await client.get(`/api/download/log/${downloadId}`)
      setLogContent(response.data.log_content)
      setSelectedLog(downloadId)
    } catch (err) {
      console.error('Error loading log:', err)
      setError(err.response?.status === 404 ? 'Log file not found' : 'Failed to load log')
      setSelectedLog(null)
      setLogContent(null)
    } finally {
      setLoadingLog(false)
    }
  }

  const closeLogModal = () => {
    setSelectedLog(null)
    setLogContent(null)
    setError(null)
  }

  if (loading) {
    return <div className="download-history-page">
      <div className="loading">Loading download history...</div>
    </div>
  }

  if (error && history.length === 0) {
    return <div className="download-history-page">
      <div className="error">{error}</div>
    </div>
  }

  return (
    <div className="download-history-page">
      <div className="download-history-header">
        <h1>Global Download History</h1>
        <p>View all completed, cancelled, and failed downloads for all users</p>
      </div>

      {history.length === 0 ? (
        <div className="empty-state">
          <p>No download history found.</p>
        </div>
      ) : (
        <>
          <div className="download-history-toolbar">
            <span className="download-history-count">{history.length} entries loaded</span>
          </div>

          <div className="download-history-table-container">
            <table className="history-table">
              <thead>
                <tr>
                  <th>Username</th>
                  <th>Device</th>
                  <th>Game</th>
                  <th>System</th>
                  <th>Version</th>
                  <th>Client</th>
                  <th>Status</th>
                  <th>Size</th>
                  <th>Date</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {history.map((item) => (
                  <tr key={item.id}>
                    <td className="username-cell">{item.username || item.user_id || '-'}</td>
                    <td className="device-cell">{item.device || '-'}</td>
                    <td className="game-cell">
                      <Link
                        to={`/game/${item.system}/${encodeURIComponent(item.rompath)}`}
                        className="game-link"
                      >
                        {item.game_name}
                      </Link>
                    </td>
                    <td className="system-cell">{item.system_name || item.system}</td>
                    <td>
                      <span className="version-tag">{item.catalog_version || 'WIP'}</span>
                    </td>
                    <td>
                      {item.client_version ? (
                        <span className="client-version-tag">{item.client_version}</span>
                      ) : (
                        <span className="no-client-version">-</span>
                      )}
                    </td>
                    <td>
                      <span className={`status-badge ${getStatusBadgeClass(item.status)}`}>
                        {item.status}
                      </span>
                    </td>
                    <td>{item.file_size ? formatBytes(item.file_size) : 'Unknown'}</td>
                    <td className="date-cell">{formatDate(item.timestamp)}</td>
                    <td>
                      <button
                        className="btn-log"
                        onClick={() => fetchLog(item.download_id)}
                        title="View download log"
                      >
                        View Log
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div ref={sentinelRef} className="scroll-sentinel">
            {loadingMore && <div className="loading-more">Loading more...</div>}
            {!hasMore && history.length > 0 && (
              <div className="no-more">All {history.length} entries loaded</div>
            )}
          </div>
        </>
      )}

      {selectedLog && (
        <div className="modal-overlay" onClick={closeLogModal}>
          <div className="modal-content log-modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>Download Log - Task {selectedLog}</h2>
              <button className="modal-close" onClick={closeLogModal}>×</button>
            </div>
            <div className="modal-body">
              {loadingLog ? (
                <div className="loading">Loading log...</div>
              ) : error ? (
                <div className="error">{error}</div>
              ) : (
                <pre className="log-content">{logContent}</pre>
              )}
            </div>
            <div className="modal-footer">
              <button className="btn-secondary" onClick={closeLogModal}>Close</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default GlobalDownloadHistory
