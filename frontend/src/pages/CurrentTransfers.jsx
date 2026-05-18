import React, { useState, useEffect, useCallback } from 'react'
import { useAuth } from '../context/AuthContext'
import client from '../api/client'
import './CurrentTransfers.css'

const REFRESH_INTERVAL = 3000

const formatBytes = (bytes) => {
  if (!bytes || bytes === 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(1024))
  return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${units[i]}`
}

const formatSpeed = (bytesPerSec) => {
  if (!bytesPerSec || bytesPerSec === 0) return null
  return `${(bytesPerSec * 8 / 1_000_000).toFixed(2)} Mbit/s`
}

const CurrentTransfers = () => {
  const { isAdmin } = useAuth()
  const [transfers, setTransfers] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [lastRefresh, setLastRefresh] = useState(null)

  const load = useCallback(async () => {
    try {
      setError(null)
      const res = await client.get('/api/download/transfers/current')
      setTransfers(res.data.transfers || [])
      setLastRefresh(new Date())
    } catch (err) {
      console.error('Error loading current transfers:', err)
      setError('Failed to load current transfers')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (!isAdmin) return
    load()
    const timer = setInterval(load, REFRESH_INTERVAL)
    return () => clearInterval(timer)
  }, [isAdmin, load])

  if (!isAdmin) {
    return (
      <div className="transfers-page">
        <div className="transfers-error"><p>Admin role required.</p></div>
      </div>
    )
  }

  const totalDownloadBw = transfers.reduce((s, t) => s + (t.bandwidth_download || 0), 0)

  const formatRefresh = (date) => {
    if (!date) return ''
    return date.toLocaleTimeString()
  }

  if (loading) return <div className="transfers-page"><div className="transfers-loading">Loading transfers…</div></div>
  if (error)   return <div className="transfers-page"><div className="transfers-error">{error}</div></div>

  return (
    <div className="transfers-page">
      <h1>Current Transfers</h1>

      <div className="transfers-summary">
        <div className="stat-card">
          <div className="stat-value">{transfers.length}</div>
          <div className="stat-label">Active Transfers</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{transfers.filter(t => t.source_type === 'direct').length}</div>
          <div className="stat-label">Direct Downloads</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{transfers.filter(t => t.source_type === 'p2p').length}</div>
          <div className="stat-label">P2P Transfers</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{formatSpeed(totalDownloadBw) || '0 Mbit/s'}</div>
          <div className="stat-label">Total Bandwidth</div>
        </div>
      </div>

      <div className="transfers-toolbar">
        <span className="transfers-refresh-info">
          Auto-refresh every {REFRESH_INTERVAL / 1000}s
          {lastRefresh && ` · Last update: ${formatRefresh(lastRefresh)}`}
        </span>
        <span className="transfers-count">{transfers.length} transfer{transfers.length !== 1 ? 's' : ''}</span>
      </div>

      <div className="transfers-table-container">
        <table className="transfers-table">
          <thead>
            <tr>
              <th>Type</th>
              <th>Source</th>
              <th>Target</th>
              <th>Game</th>
              <th>System</th>
              <th>Queue</th>
              <th>Progress</th>
              <th>Download Speed</th>
            </tr>
          </thead>
          <tbody>
            {transfers.length === 0 ? (
              <tr><td colSpan={8} className="no-transfers">No active transfers</td></tr>
            ) : (
              transfers.map(t => {
                const speed = formatSpeed(t.bandwidth_download)
                return (
                  <tr key={t.id}>
                    <td>
                      <span className={`type-badge type-badge--${t.source_type}`}>
                        {t.source_type === 'p2p' ? '⇄ P2P' : '↓ Direct'}
                      </span>
                    </td>
                    <td className="source-cell">
                      {t.source_username && (
                        <div className="source-username">{t.source_username}</div>
                      )}
                      <div className="source-token">{t.source_name}</div>
                    </td>
                    <td className="target-cell">
                      <div className="target-username">{t.target_username}</div>
                      {t.target_token_name && (
                        <div className="target-token">{t.target_token_name}</div>
                      )}
                    </td>
                    <td className="game-cell" title={t.game_name}>{t.game_name}</td>
                    <td className="system-cell">
                      {t.system_name || t.system || '—'}
                    </td>
                    <td>
                      <span className={`queue-badge queue-badge--${t.queue_type}`}>
                        {t.queue_type}
                      </span>
                    </td>
                    <td className="progress-cell">
                      {t.file_size ? (
                        <div className="progress-bar-wrap">
                          <div className="progress-bar">
                            <div
                              className="progress-bar-fill"
                              style={{ width: `${t.progress_percent}%` }}
                            />
                          </div>
                          <span className="progress-pct">{t.progress_percent}%</span>
                        </div>
                      ) : (
                        <span style={{ color: 'var(--text-secondary)' }}>—</span>
                      )}
                    </td>
                    <td className={`bw-cell${!speed ? ' bw-cell--zero' : ''}`}>
                      {speed || '—'}
                    </td>
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default CurrentTransfers
