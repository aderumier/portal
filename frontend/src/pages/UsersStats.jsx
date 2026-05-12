import React, { useState, useEffect, useMemo } from 'react'
import { useAuth } from '../context/AuthContext'
import client from '../api/client'
import './UsersStats.css'

const COLUMNS = [
  { key: 'username',              label: 'Username',         sortFn: (a, b) => (a.username || '').localeCompare(b.username || '') },
  { key: 'total_download_mb',     label: 'Downloaded',       sortFn: (a, b) => a.total_download_mb - b.total_download_mb },
  { key: 'total_download_number', label: 'Games',            sortFn: (a, b) => a.total_download_number - b.total_download_number },
  { key: 'p2p_total_download_mb', label: 'P2P Down',         sortFn: (a, b) => (a.p2p_total_download_mb || 0) - (b.p2p_total_download_mb || 0) },
  { key: 'p2p_total_upload_mb',   label: 'P2P Up',           sortFn: (a, b) => (a.p2p_total_upload_mb || 0) - (b.p2p_total_upload_mb || 0) },
  { key: 'medias_upload',         label: 'Medias Up',        sortFn: (a, b) => (a.medias_upload || 0) - (b.medias_upload || 0) },
  { key: 'medias_validated',      label: 'Medias Valid.',    sortFn: (a, b) => (a.medias_validated || 0) - (b.medias_validated || 0) },
  { key: 'last_login_ip',         label: 'Last Login IP',    sortFn: (a, b) => (a.last_login_ip || '').localeCompare(b.last_login_ip || '') },
  { key: 'country',               label: 'Country',          sortFn: (a, b) => (a.country || '').localeCompare(b.country || '') },
  { key: 'torrent_locked_ips',    label: 'Torrent IPs',      sortFn: null },
  { key: 'last_login',            label: 'Last Login',       sortFn: (a, b) => (a.last_login || '').localeCompare(b.last_login || '') },
  { key: 'created_at',            label: 'Created',          sortFn: (a, b) => (a.created_at || '').localeCompare(b.created_at || '') },
]

const UsersStats = () => {
  const { isAdmin } = useAuth()
  const [users, setUsers] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [search, setSearch] = useState('')
  const [sortKey, setSortKey] = useState('total_download_mb')
  const [sortDir, setSortDir] = useState('desc')

  useEffect(() => {
    if (isAdmin) loadUsersStats()
  }, [isAdmin])

  const loadUsersStats = async () => {
    try {
      setLoading(true)
      setError(null)
      const response = await client.get('/api/users/stats')
      setUsers(response.data.users || [])
    } catch (err) {
      console.error('Error loading users stats:', err)
      setError('Failed to load users statistics')
    } finally {
      setLoading(false)
    }
  }

  const resetTorrentIp = async (userId) => {
    try {
      await client.delete(`/api/admin/users/${userId}/torrent-ip`)
      setUsers(prev => prev.map(u =>
        u.user_id === userId ? { ...u, torrent_locked_ips: [] } : u
      ))
    } catch (err) {
      console.error('Error resetting torrent IP:', err)
    }
  }

  const handleSort = (key) => {
    const col = COLUMNS.find(c => c.key === key)
    if (!col?.sortFn) return
    if (sortKey === key) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    } else {
      setSortKey(key)
      setSortDir('desc')
    }
  }

  const displayedUsers = useMemo(() => {
    const col = COLUMNS.find(c => c.key === sortKey)
    let list = search
      ? users.filter(u => (u.username || u.user_id || '').toLowerCase().includes(search.toLowerCase()))
      : users
    if (col?.sortFn) {
      list = [...list].sort((a, b) => sortDir === 'asc' ? col.sortFn(a, b) : col.sortFn(b, a))
    }
    return list
  }, [users, search, sortKey, sortDir])

  const formatDate = (dateStr) => {
    if (!dateStr) return 'Never'
    try { return new Date(dateStr).toLocaleString() } catch { return dateStr }
  }

  const formatMB = (mb) => {
    if (!mb) return '0 MB'
    return mb < 1024 ? `${mb.toFixed(2)} MB` : `${(mb / 1024).toFixed(2)} GB`
  }

  const formatTimeAgo = (dateStr) => {
    if (!dateStr) return 'Never'
    try {
      const diff = Date.now() - new Date(dateStr)
      const d = Math.floor(diff / 86400000)
      const h = Math.floor(diff / 3600000)
      const m = Math.floor(diff / 60000)
      if (d > 0) return `${d}d ago`
      if (h > 0) return `${h}h ago`
      if (m > 0) return `${m}m ago`
      return 'Just now'
    } catch { return dateStr }
  }

  const getCountryFlag = (code) => {
    if (!code) return null
    return String.fromCodePoint(...code.toUpperCase().split('').map(c => 127397 + c.charCodeAt()))
  }

  const SortIcon = ({ col }) => {
    if (!col.sortFn) return null
    if (sortKey !== col.key) return <span className="sort-icon sort-icon--idle">↕</span>
    return <span className="sort-icon">{sortDir === 'asc' ? '↑' : '↓'}</span>
  }

  if (!isAdmin) {
    return (
      <div className="users-stats-page">
        <div className="users-stats-error"><p>You must have Admin role to access users statistics.</p></div>
      </div>
    )
  }

  if (loading) return <div className="users-stats-page"><div className="users-stats-loading">Loading users statistics...</div></div>
  if (error)   return <div className="users-stats-page"><div className="users-stats-error">{error}</div></div>

  return (
    <div className="users-stats-page">
      <h1>Users Statistics</h1>

      <div className="users-stats-summary">
        <div className="stat-card">
          <div className="stat-value">{users.length}</div>
          <div className="stat-label">Total Users</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{formatMB(users.reduce((s, u) => s + u.total_download_mb, 0))}</div>
          <div className="stat-label">Total Downloaded</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{users.reduce((s, u) => s + u.total_download_number, 0)}</div>
          <div className="stat-label">Total Games Downloaded</div>
        </div>
      </div>

      <div className="users-table-toolbar">
        <input
          className="users-search"
          type="search"
          placeholder="Search username…"
          value={search}
          onChange={e => setSearch(e.target.value)}
        />
        <span className="users-count">{displayedUsers.length} / {users.length} users</span>
      </div>

      <div className="users-table-container">
        <table className="users-table">
          <thead>
            <tr>
              {COLUMNS.map(col => (
                <th
                  key={col.key}
                  className={col.sortFn ? 'sortable' : ''}
                  onClick={() => handleSort(col.key)}
                >
                  {col.label}<SortIcon col={col} />
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {displayedUsers.length === 0 ? (
              <tr><td colSpan={COLUMNS.length} className="no-users">No users found</td></tr>
            ) : (
              displayedUsers.map((user) => (
                <tr key={user.user_id}>
                  <td className="username-cell">{user.username || user.user_id}</td>
                  <td className="download-mb-cell">{formatMB(user.total_download_mb)}</td>
                  <td className="download-number-cell">{user.total_download_number}</td>
                  <td>{formatMB(user.p2p_total_download_mb || 0)}</td>
                  <td>{formatMB(user.p2p_total_upload_mb || 0)}</td>
                  <td className="num-cell">{user.medias_upload || 0}</td>
                  <td className="num-cell">{user.medias_validated || 0}</td>
                  <td className="mono-cell">{user.last_login_ip || '-'}</td>
                  <td className="country-cell">
                    {user.country
                      ? <span className="country-flag" title={user.country}>{getCountryFlag(user.country)}</span>
                      : '-'}
                  </td>
                  <td className="torrent-ips-cell">
                    {user.torrent_locked_ips?.length > 0 ? (
                      <div className="torrent-ips">
                        <span className="torrent-ip-count">
                          {user.torrent_locked_ips.length} IP{user.torrent_locked_ips.length > 1 ? 's' : ''}
                          <span className="torrent-ip-tooltip">
                            {user.torrent_locked_ips.map(ip => <span key={ip}>{ip}</span>)}
                          </span>
                        </span>
                        <button
                          className="reset-torrent-ip-btn"
                          onClick={() => resetTorrentIp(user.user_id)}
                          title="Clear torrent IP lock"
                        >✕</button>
                      </div>
                    ) : <span className="torrent-ips-none">—</span>}
                  </td>
                  <td className="last-login-cell">
                    <span title={formatDate(user.last_login)}>{formatTimeAgo(user.last_login)}</span>
                  </td>
                  <td className="created-at-cell">
                    <span title={formatDate(user.created_at)}>{formatDate(user.created_at)}</span>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default UsersStats
