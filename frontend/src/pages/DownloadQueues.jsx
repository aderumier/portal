import React, { useState, useEffect } from 'react'
import { useAuth } from '../context/AuthContext'
import { getMediaUrl } from '../utils/constants'
import client from '../api/client'
import './DownloadQueues.css'

const DownloadQueues = () => {
  const { isAdmin } = useAuth()
  const [queues, setQueues] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (isAdmin) {
      loadQueues()
      // Refresh every 5 seconds
      const interval = setInterval(loadQueues, 5000)
      return () => clearInterval(interval)
    }
  }, [isAdmin])

  const loadQueues = async () => {
    try {
      setError(null)
      const response = await client.get('/api/download/queues/all')
      setQueues(response.data)
    } catch (err) {
      console.error('Error loading download queues:', err)
      setError('Failed to load download queues')
    } finally {
      setLoading(false)
    }
  }

  const handleRemoveFromQueue = async (userId, gameId) => {
    if (!window.confirm('Are you sure you want to remove this game from the queue?')) {
      return
    }

    try {
      // URL encode the game ID
      const encodedGameId = encodeURIComponent(gameId)
      await client.delete(`/api/download/queue/admin/${userId}/${encodedGameId}`)
      // Refresh queues
      loadQueues()
    } catch (err) {
      console.error('Error removing from queue:', err)
      alert('Failed to remove from queue')
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

  const formatDuration = (startedAt) => {
    if (!startedAt) return 'N/A'
    const start = new Date(startedAt)
    const now = new Date()
    const diff = Math.floor((now - start) / 1000) // seconds

    if (diff < 60) return `${diff}s`
    if (diff < 3600) return `${Math.floor(diff / 60)}m ${diff % 60}s`
    const hours = Math.floor(diff / 3600)
    const minutes = Math.floor((diff % 3600) / 60)
    return `${hours}h ${minutes}m`
  }

  if (!isAdmin) {
    return (
      <div className="download-queues-page">
        <div className="download-queues-error">
          <p>You must have Admin role to access download queues.</p>
        </div>
      </div>
    )
  }

  if (loading && !queues) {
    return (
      <div className="download-queues-page">
        <div className="download-queues-loading">Loading download queues...</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="download-queues-page">
        <div className="download-queues-error">{error}</div>
      </div>
    )
  }

  return (
    <div className="download-queues-page">
      <h1>Download Queues</h1>

      <div className="queues-stats">
        <div className="stat-card">
          <div className="stat-value">{queues?.total_active || 0}</div>
          <div className="stat-label">Active Downloads</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{queues?.total_user_queue || 0}</div>
          <div className="stat-label">User Queue (Waiting)</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{queues?.fast_queue?.length || 0}</div>
          <div className="stat-label">Fast Queue (Total)</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{queues?.slow_queue?.length || 0}</div>
          <div className="stat-label">Slow Queue (Total)</div>
        </div>
      </div>

      <div className="queues-container">
        {/* User Queue Section */}


        {/* Active Downloads Section */}
        <div className="queue-section">
          <h2 className="queue-title fast-queue">
            Fast Queue - Active ({queues?.downloading_fast?.length || 0})
          </h2>
          {queues?.downloading_fast?.length === 0 ? (
            <p className="no-downloads">No active downloads in fast queue</p>
          ) : (
            <div className="downloads-list">
              {queues?.downloading_fast?.map((download) => (
                <div key={download.id} className="download-item">
                  <div className="download-item-image">
                    {download.image ? (
                      <img src={getMediaUrl(download.image)} alt={download.game_name} />
                    ) : (
                      <div className="no-image">No Image</div>
                    )}
                  </div>
                  <div className="download-item-info">
                    <div className="download-item-header">
                      <h3>{download.game_name}</h3>
                      <span className={`status-badge status-${download.status}`}>
                        {download.status}
                      </span>
                    </div>
                    <div className="download-item-details">
                      <div className="detail-row">
                        <span className="detail-label">System:</span>
                        <span className="detail-value">{download.system_name || download.system}</span>
                      </div>
                      <div className="detail-row">
                        <span className="detail-label">Version:</span>
                        <span className="detail-value">{download.catalog_version || 'WIP'}</span>
                      </div>
                      {download.client_version && (
                        <div className="detail-row">
                          <span className="detail-label">Client:</span>
                          <span className="detail-value">{download.client_version}</span>
                        </div>
                      )}
                      <div className="detail-row">
                        <span className="detail-label">User:</span>
                        <span className="detail-value">{download.username || download.user_id}</span>
                      </div>
                      {download.assigned_to_service && (
                        <div className="detail-row">
                          <span className="detail-label">Service:</span>
                          <span className="detail-value">{download.assigned_to_service}</span>
                        </div>
                      )}
                    </div>
                    {download.active_download && download.file_size && (
                      <div className="download-progress">
                        <div className="progress-bar-container">
                          <div
                            className="progress-bar"
                            style={{ width: `${download.progress_percent}%` }}
                          />
                        </div>
                        <div className="progress-info">
                          <span>{download.progress_percent}%</span>
                          <span>{formatBytes(download.bytes_transferred)} / {formatBytes(download.file_size)}</span>
                          {download.bandwidth_used > 0 && (
                            <span className="bandwidth">{formatBytesPerSecond(download.bandwidth_used)}</span>
                          )}
                        </div>
                      </div>
                    )}
                    {download.started_at && (
                      <div className="download-meta">
                        <span>Started: {formatDuration(download.started_at)} ago</span>
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="queue-section">
          <h2 className="queue-title slow-queue">
            Slow Queue - Active ({queues?.downloading_slow?.length || 0})
          </h2>
          {queues?.downloading_slow?.length === 0 ? (
            <p className="no-downloads">No active downloads in slow queue</p>
          ) : (
            <div className="downloads-list">
              {queues?.downloading_slow?.map((download) => (
                <div key={download.id} className="download-item">
                  <div className="download-item-image">
                    {download.image ? (
                      <img src={getMediaUrl(download.image)} alt={download.game_name} />
                    ) : (
                      <div className="no-image">No Image</div>
                    )}
                  </div>
                  <div className="download-item-info">
                    <div className="download-item-header">
                      <h3>{download.game_name}</h3>
                      <span className={`status-badge status-${download.status}`}>
                        {download.status}
                      </span>
                    </div>
                    <div className="download-item-details">
                      <div className="detail-row">
                        <span className="detail-label">System:</span>
                        <span className="detail-value">{download.system_name || download.system}</span>
                      </div>
                      <div className="detail-row">
                        <span className="detail-label">Version:</span>
                        <span className="detail-value">{download.catalog_version || 'WIP'}</span>
                      </div>
                      {download.client_version && (
                        <div className="detail-row">
                          <span className="detail-label">Client:</span>
                          <span className="detail-value">{download.client_version}</span>
                        </div>
                      )}
                      <div className="detail-row">
                        <span className="detail-label">User:</span>
                        <span className="detail-value">{download.username || download.user_id}</span>
                      </div>
                      {download.assigned_to_service && (
                        <div className="detail-row">
                          <span className="detail-label">Service:</span>
                          <span className="detail-value">{download.assigned_to_service}</span>
                        </div>
                      )}
                    </div>
                    {download.active_download && download.file_size && (
                      <div className="download-progress">
                        <div className="progress-bar-container">
                          <div
                            className="progress-bar"
                            style={{ width: `${download.progress_percent}%` }}
                          />
                        </div>
                        <div className="progress-info">
                          <span>{download.progress_percent}%</span>
                          <span>{formatBytes(download.bytes_transferred)} / {formatBytes(download.file_size)}</span>
                          {download.bandwidth_used > 0 && (
                            <span className="bandwidth">{formatBytesPerSecond(download.bandwidth_used)}</span>
                          )}
                        </div>
                      </div>
                    )}
                    {download.started_at && (
                      <div className="download-meta">
                        <span>Started: {formatDuration(download.started_at)} ago</span>
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* User Queue Table Section - Moved to bottom */}
        <div className="queue-section user-queue-section">
          <h2 className="queue-title user-queue">
            User Queues ({queues?.total_user_queue || 0})
          </h2>
          <p className="queue-description">Downloads waiting in user queues</p>

          <div className="user-queue-table-container">
            <table className="user-queue-table">
              <thead>
                <tr>
                  <th>Game</th>
                  <th>System</th>
                  <th>Version</th>
                  <th>User</th>
                  <th>Type</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {[...(queues?.user_queue_fast || []), ...(queues?.user_queue_slow || [])].length === 0 ? (
                  <tr>
                    <td colSpan="6" className="no-data">No items in user queues</td>
                  </tr>
                ) : (
                  [...(queues?.user_queue_fast || []), ...(queues?.user_queue_slow || [])].map((download) => (
                    <tr key={download.id}>
                      <td className="game-cell">
                        <div className="game-info">
                          {download.image && (
                            <img src={getMediaUrl(download.image)} alt={download.game_name} className="mini-thumb" />
                          )}
                          <span>{download.game_name}</span>
                        </div>
                      </td>
                      <td>{download.system_name || download.system}</td>
                      <td>{download.catalog_version || 'WIP'}</td>
                      <td>{download.username || download.user_id}</td>
                      <td>
                        <span className={`queue-badge ${queues?.user_queue_fast?.some(d => d.id === download.id) ? 'fast' : 'slow'}`}>
                          {queues?.user_queue_fast?.some(d => d.id === download.id) ? 'Fast' : 'Slow'}
                        </span>
                      </td>
                      <td>
                        <button
                          className="remove-btn small"
                          onClick={() => handleRemoveFromQueue(download.user_id, download.game_id)}
                          title="Remove from queue"
                        >
                          Remove
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  )
}

export default DownloadQueues

