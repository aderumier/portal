import React, { useState, useEffect, useRef, useCallback } from 'react'
import { Link } from 'react-router-dom'
import client from '../api/client'
import {
  useTableSortFilter, SortIcon, ColumnFilter,
  cmpText, cmpNum, cmpAuto, cmpDate,
} from '../utils/tableSort'
import './DownloadHistory.css'

const PAGE_SIZE = 100

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

const COLUMNS = [
  { key: 'username',        label: 'Username', sortFn: (a, b) => cmpText(a.username || a.user_id, b.username || b.user_id),        filterValue: i => i.username || i.user_id || '-' },
  { key: 'device',          label: 'Device',   sortFn: (a, b) => cmpText(a.device, b.device),                                      filterValue: i => i.device || '-' },
  { key: 'game_name',       label: 'Game',     sortFn: (a, b) => cmpText(a.game_name, b.game_name),                                filterValue: i => i.game_name },
  { key: 'system',          label: 'System',   sortFn: (a, b) => cmpText(a.system_name || a.system, b.system_name || b.system),    filterValue: i => i.system_name || i.system },
  { key: 'catalog_version', label: 'Version',  sortFn: (a, b) => cmpAuto(a.catalog_version || 'WIP', b.catalog_version || 'WIP'),  filterValue: i => i.catalog_version || 'WIP' },
  { key: 'client_version',  label: 'Client',   sortFn: (a, b) => cmpAuto(a.client_version, b.client_version),                      filterValue: i => i.client_version || '-' },
  { key: 'status',          label: 'Status',   sortFn: (a, b) => cmpText(a.status, b.status),                                      filterValue: i => i.status },
  { key: 'file_size',       label: 'Size',     sortFn: (a, b) => cmpNum(a.file_size, b.file_size),                                 filterValue: i => (i.file_size ? formatBytes(i.file_size) : 'Unknown') },
  { key: 'timestamp',       label: 'Date',     sortFn: (a, b) => cmpDate(a.timestamp, b.timestamp),                                filterValue: i => formatDate(i.timestamp) },
  { key: 'actions',         label: 'Actions',  sortFn: null,                                                                       filterValue: null },
]

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

  // Sorting and filtering apply to the entries already loaded, not to the whole
  // server-side history, since the endpoint only paginates.
  const {
    sortKey, sortDir, handleSort,
    filters, setFilter, clearFilters, activeFilterCount,
    displayedRows,
  } = useTableSortFilter(history, COLUMNS)

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
            <span className="download-history-count">
              {activeFilterCount > 0
                ? `${displayedRows.length} / ${history.length} entries loaded`
                : `${history.length} entries loaded`}
            </span>
            {activeFilterCount > 0 && (
              <button className="clear-filters-btn" onClick={clearFilters}>Clear filters</button>
            )}
          </div>

          <div className="download-history-table-container">
            <table className="history-table">
              <thead>
                <tr>
                  {COLUMNS.map(col => (
                    <th
                      key={col.key}
                      className={col.sortFn ? 'sortable' : ''}
                      onClick={() => handleSort(col.key)}
                    >
                      {col.label}<SortIcon col={col} sortKey={sortKey} sortDir={sortDir} />
                    </th>
                  ))}
                </tr>
                <tr className="filter-row">
                  {COLUMNS.map(col => (
                    <th key={col.key}>
                      <ColumnFilter col={col} filters={filters} setFilter={setFilter} />
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {displayedRows.length === 0 && (
                  <tr>
                    <td colSpan={COLUMNS.length} className="no-matches">
                      No loaded entries match the current filters
                    </td>
                  </tr>
                )}
                {displayedRows.map((item) => (
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
