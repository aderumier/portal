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
          <div className="stat-value">{queues?.total_pending || 0}</div>
          <div className="stat-label">Pending Downloads</div>
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
        {(queues?.user_queue_fast?.length > 0 || queues?.user_queue_slow?.length > 0) && (
          <div className="queue-section user-queue-section">
            <h2 className="queue-title user-queue">
              User Queue ({queues?.total_user_queue || 0})
            </h2>
            <p className="queue-description">Games waiting to be promoted to download queues when download service connects</p>
            
            {queues?.user_queue_fast?.length > 0 && (
              <div className="user-queue-subsection">
                <h3 className="sub-queue-title">Fast Queue ({queues.user_queue_fast.length})</h3>
                <div className="downloads-list">
                  {queues.user_queue_fast.map((download) => (
                    <div key={download.id} className="download-item user-queue-item">
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
                          <span className="status-badge status-user_queue">User Queue</span>
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
                          <div className="detail-row">
                            <span className="detail-label">User:</span>
                            <span className="detail-value">{download.username || download.user_id}</span>
                          </div>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
            
            {queues?.user_queue_slow?.length > 0 && (
              <div className="user-queue-subsection">
                <h3 className="sub-queue-title">Slow Queue ({queues.user_queue_slow.length})</h3>
                <div className="downloads-list">
                  {queues.user_queue_slow.map((download) => (
                    <div key={download.id} className="download-item user-queue-item">
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
                          <span className="status-badge status-user_queue">User Queue</span>
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
                          <div className="detail-row">
                            <span className="detail-label">User:</span>
                            <span className="detail-value">{download.username || download.user_id}</span>
                          </div>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Pending Downloads Section */}
        {(queues?.pending_fast?.length > 0 || queues?.pending_slow?.length > 0) && (
          <div className="queue-section pending-section">
            <h2 className="queue-title pending-queue">
              Pending Downloads ({queues?.total_pending || 0})
            </h2>
            <p className="queue-description">Games ready to be downloaded, waiting for download service</p>
            
            {queues?.pending_fast?.length > 0 && (
              <div className="pending-subsection">
                <h3 className="sub-queue-title">Fast Queue ({queues.pending_fast.length})</h3>
                <div className="downloads-list">
                  {queues.pending_fast.map((download) => (
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
                          <span className="status-badge status-pending">Pending</span>
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
                          <div className="detail-row">
                            <span className="detail-label">User:</span>
                            <span className="detail-value">{download.username || download.user_id}</span>
                          </div>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
            
            {queues?.pending_slow?.length > 0 && (
              <div className="pending-subsection">
                <h3 className="sub-queue-title">Slow Queue ({queues.pending_slow.length})</h3>
                <div className="downloads-list">
                  {queues.pending_slow.map((download) => (
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
                          <span className="status-badge status-pending">Pending</span>
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
                          <div className="detail-row">
                            <span className="detail-label">User:</span>
                            <span className="detail-value">{download.username || download.user_id}</span>
                          </div>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

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
      </div>
    </div>
  )
}

export default DownloadQueues

