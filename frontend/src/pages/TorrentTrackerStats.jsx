import React, { useState, useEffect, useMemo } from 'react'
import { useAuth } from '../context/AuthContext'
import client from '../api/client'
import './TorrentTrackerStats.css'

const SWARM_COLUMNS = [
  { key: 'system_name', label: 'System',   num: false },
  { key: 'info_hash',   label: 'Info Hash', num: false },
  { key: 'private',     label: 'Private',   num: false },
  { key: 'seeders',     label: 'Seeds',     num: true  },
  { key: 'leechers',    label: 'Leechers',  num: true  },
  { key: 'total_peers', label: 'Total',     num: true  },
]

const TorrentTrackerStats = () => {
  const { isAdmin } = useAuth()
  const [swarms, setSwarms]               = useState([])
  const [loading, setLoading]             = useState(true)
  const [error, setError]                 = useState(null)
  const [sortKey, setSortKey]             = useState('total_peers')
  const [sortDir, setSortDir]             = useState('desc')
  // Modal state
  const [modalSwarm, setModalSwarm]       = useState(null)
  const [peers, setPeers]                 = useState([])
  const [peersLoading, setPeersLoading]   = useState(false)
  const [peersError, setPeersError]       = useState(null)

  useEffect(() => {
    if (isAdmin) loadSwarms()
  }, [isAdmin])

  const loadSwarms = async () => {
    try {
      setLoading(true)
      setError(null)
      const res = await client.get('/api/admin/tracker/swarms')
      setSwarms(res.data.swarms || [])
    } catch {
      setError('Failed to load tracker swarms. Is Redis reachable?')
    } finally {
      setLoading(false)
    }
  }

  const openModal = async (swarm) => {
    setModalSwarm(swarm)
    setPeers([])
    setPeersError(null)
    setPeersLoading(true)
    try {
      const res = await client.get(`/api/admin/tracker/swarms/${swarm.info_hash}/peers`)
      setPeers(res.data.peers || [])
    } catch {
      setPeersError('Failed to load peer details.')
    } finally {
      setPeersLoading(false)
    }
  }

  const closeModal = () => {
    setModalSwarm(null)
    setPeers([])
    setPeersError(null)
  }

  const handleSort = (key) => {
    if (sortKey === key) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    } else {
      setSortKey(key)
      setSortDir('desc')
    }
  }

  const sortedSwarms = useMemo(() => {
    const col = SWARM_COLUMNS.find(c => c.key === sortKey)
    return [...swarms].sort((a, b) => {
      const av = a[sortKey] ?? (col?.num ? 0 : '')
      const bv = b[sortKey] ?? (col?.num ? 0 : '')
      if (col?.num) return sortDir === 'asc' ? av - bv : bv - av
      return sortDir === 'asc'
        ? String(av).localeCompare(String(bv))
        : String(bv).localeCompare(String(av))
    })
  }, [swarms, sortKey, sortDir])

  const sortArrow = (key) => sortKey === key ? (sortDir === 'asc' ? ' ▲' : ' ▼') : ''

  if (!isAdmin) return null

  const totalSeeders  = swarms.reduce((s, x) => s + x.seeders, 0)
  const totalLeechers = swarms.reduce((s, x) => s + x.leechers, 0)

  return (
    <div className="tracker-stats-page">
      <div className="tracker-stats-header">
        <h1>Torrent Tracker Stats</h1>
        <button className="tts-refresh-btn" onClick={loadSwarms} disabled={loading}>
          {loading ? 'Loading…' : 'Refresh'}
        </button>
      </div>

      {error && <div className="message message-error">{error}</div>}

      {!loading && swarms.length > 0 && (
        <div className="tts-summary">
          <span className="tts-summary-item"><strong>{swarms.length}</strong> swarms</span>
          <span className="tts-summary-sep">·</span>
          <span className="tts-summary-item tts-seeds"><strong>{totalSeeders}</strong> seeders</span>
          <span className="tts-summary-sep">·</span>
          <span className="tts-summary-item tts-leechers"><strong>{totalLeechers}</strong> leechers</span>
        </div>
      )}

      <table className="tts-table">
        <thead>
          <tr>
            {SWARM_COLUMNS.map(col => (
              <th key={col.key} onClick={() => handleSort(col.key)}>
                {col.label}{sortArrow(col.key)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {loading ? (
            <tr><td colSpan={6} className="tts-cell-center">Loading swarms…</td></tr>
          ) : sortedSwarms.length === 0 ? (
            <tr><td colSpan={6} className="tts-cell-center tts-empty">No active swarms found.</td></tr>
          ) : sortedSwarms.map(swarm => (
            <tr key={swarm.info_hash} onClick={() => openModal(swarm)} className="tts-row">
              <td>{swarm.system_name ?? <span className="tts-unknown">—</span>}</td>
              <td className="tts-mono">{swarm.info_hash.slice(0, 16)}…</td>
              <td>
                {swarm.private === null
                  ? <span className="tts-unknown">—</span>
                  : swarm.private
                    ? <span className="tts-badge tts-badge-seeder">Yes</span>
                    : <span className="tts-badge tts-badge-leecher">No</span>}
              </td>
              <td className="tts-seeds">{swarm.seeders}</td>
              <td className="tts-leechers">{swarm.leechers}</td>
              <td><strong>{swarm.total_peers}</strong></td>
            </tr>
          ))}
        </tbody>
      </table>

      {/* Peers modal */}
      {modalSwarm && (
        <div className="tts-modal-backdrop" onClick={closeModal}>
          <div className="tts-modal" onClick={e => e.stopPropagation()}>
            <div className="tts-modal-header">
              <h2>
                Peers — {modalSwarm.system_name ?? modalSwarm.info_hash.slice(0, 16) + '…'}
                <span className="tts-modal-ih"> ({modalSwarm.info_hash.slice(0, 16)}…)</span>
              </h2>
              <div className="tts-modal-actions">
                {!peersLoading && (
                  <button className="tts-refresh-btn tts-refresh-btn-sm" onClick={() => openModal(modalSwarm)}>
                    Refresh
                  </button>
                )}
                <button className="tts-modal-close" onClick={closeModal}>✕</button>
              </div>
            </div>

            <div className="tts-modal-body">
              {peersError && <div className="message message-error">{peersError}</div>}

              {peersLoading ? (
                <div className="tts-cell-center">Loading peers…</div>
              ) : (
                <table className="tts-table">
                  <thead>
                    <tr>
                      <th>Username</th>
                      <th>IP Address</th>
                      <th>Port</th>
                      <th>Role</th>
                    </tr>
                  </thead>
                  <tbody>
                    {peers.length === 0 ? (
                      <tr><td colSpan={4} className="tts-cell-center tts-empty">No peers currently active.</td></tr>
                    ) : peers.map((p, i) => (
                      <tr key={i}>
                        <td>
                          {p.username
                            ? <strong>{p.username}</strong>
                            : <span className="tts-unknown">unknown</span>}
                        </td>
                        <td className="tts-mono">{p.ip}</td>
                        <td>{p.port}</td>
                        <td>
                          <span className={`tts-badge ${p.seeder ? 'tts-badge-seeder' : 'tts-badge-leecher'}`}>
                            {p.seeder ? 'Seeder' : 'Leecher'}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default TorrentTrackerStats
