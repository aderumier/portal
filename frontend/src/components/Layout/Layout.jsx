import React, { useState, useRef, useEffect } from 'react'
import { Outlet, Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'
import { useCatalog } from '../../context/CatalogContext'
import client from '../../api/client'

import './Layout.css'
import HeaderSearch from './HeaderSearch'
import { refreshCatalog, getRefreshStatus } from '../../api/catalog'

const Layout = () => {
  const { user, isAuthenticated, isAdmin, isDownload, isFastDownload, logout } = useAuth()
  const { canContribute, canViewReleases, canViewWip } = useCatalog()
  const navigate = useNavigate()
  const [accountMenuOpen, setAccountMenuOpen] = useState(false)
  const [playlistMenuOpen, setPlaylistMenuOpen] = useState(false)
  const accountMenuRef = useRef(null)
  const playlistMenuRef = useRef(null)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [pendingMediaCount, setPendingMediaCount] = useState(0)
  const [showPendingModal, setShowPendingModal] = useState(false)

  const handleLogout = () => {
    logout()
    setAccountMenuOpen(false)
  }

  // The rebuild takes minutes, so the request only starts it and we poll for the outcome.
  // Waiting on the request itself just means the proxy times out and reports a failure for a
  // refresh that is still running perfectly well.
  const handleRefreshCatalog = async () => {
    setIsRefreshing(true)
    setAccountMenuOpen(false)
    try {
      await refreshCatalog()

      while (true) {
        await new Promise((resolve) => setTimeout(resolve, 5000))

        let status
        try {
          status = await getRefreshStatus()
        } catch (error) {
          // A blip while polling says nothing about the refresh itself; keep waiting.
          console.error('Error polling catalog refresh status:', error)
          continue
        }

        if (status.state === 'completed') {
          const result = status.result || {}
          alert(`Catalog refreshed successfully!\nSystems: ${result.systems_count}\nTotal games: ${result.total_games}`)
          return
        }
        if (status.state === 'failed') {
          console.error('Catalog refresh failed:', status.error)
          alert(`Failed to refresh catalog: ${status.error || 'unknown error'}`)
          return
        }
        if (status.state !== 'running') {
          return
        }
      }
    } catch (error) {
      console.error('Error starting catalog refresh:', error)
      alert('Failed to start catalog refresh. Please try again.')
    } finally {
      setIsRefreshing(false)
    }
  }

  // Close menu when clicking outside
  useEffect(() => {
    const handleClickOutside = (event) => {
      if (accountMenuRef.current && !accountMenuRef.current.contains(event.target)) {
        setAccountMenuOpen(false)
      }
      if (playlistMenuRef.current && !playlistMenuRef.current.contains(event.target)) {
        setPlaylistMenuOpen(false)
      }
    }

    if (accountMenuOpen || playlistMenuOpen) {
      document.addEventListener('mousedown', handleClickOutside)
    }

    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
    }
  }, [accountMenuOpen, playlistMenuOpen])

  useEffect(() => {
    if (!isAdmin) return
    let firstFetch = true
    const fetchCount = async () => {
      try {
        const res = await client.get('/api/media/pending-count')
        const count = res.data.count || 0
        setPendingMediaCount(count)
        if (firstFetch && count > 0 && !sessionStorage.getItem('pendingMediaModalShown')) {
          setShowPendingModal(true)
          sessionStorage.setItem('pendingMediaModalShown', '1')
        }
      } catch {
        // silently ignore
      } finally {
        firstFetch = false
      }
    }
    fetchCount()
    const interval = setInterval(fetchCount, 60000)
    return () => clearInterval(interval)
  }, [isAdmin])

  const handlePendingModalClose = () => setShowPendingModal(false)

  const handlePendingModalValidate = () => {
    setShowPendingModal(false)
    navigate('/media-validation')
  }

  return (
    <div className="layout">
      <header className="header">
        <div className="header-content">
          <Link to="/" className="logo">
            <img src="/logo.png" alt="Team Pixel Nostalgia" className="logo-image" />
          </Link>
          {isAuthenticated && <HeaderSearch />}
          <nav className="nav">
            {isAuthenticated ? (
              <>
                {canViewWip && <Link to="/wip">WIP</Link>}
                {canViewReleases && <Link to="/releases">Releases</Link>}
                {canContribute && (
                  <div className="contribute-menu">
                    <Link to="/contribute" className="contribute-menu-trigger">Contribute</Link>
                    <div className="contribute-menu-dropdown">
                      <Link to="/contribute" className="contribute-menu-item">Game List</Link>
                      <Link to="/contribute/my-pending" className="contribute-menu-item">My Pending Media</Link>
                    </div>
                  </div>
                )}

                <div className="playlist-menu" ref={playlistMenuRef}>
                  <button
                    className="playlist-menu-trigger"
                    onClick={() => setPlaylistMenuOpen(!playlistMenuOpen)}
                  >
                    Playlists
                  </button>
                  {playlistMenuOpen && (
                    <div className="playlist-menu-dropdown">
                      <Link to="/playlist/collections" className="playlist-menu-item" onClick={() => setPlaylistMenuOpen(false)}>Collections</Link>
                      <Link to="/playlist/top-downloads" className="playlist-menu-item" onClick={() => setPlaylistMenuOpen(false)}>Top Download</Link>
                      <Link to="/playlist/top-played" className="playlist-menu-item" onClick={() => setPlaylistMenuOpen(false)}>Top Played Games</Link>
                    </div>
                  )}
                </div>

                {(isDownload || isFastDownload) && (
                  <div className="downloads-menu">
                    <Link to="/downloads" className="downloads-menu-trigger">Downloads</Link>
                    <div className="downloads-menu-dropdown">
                      <Link to="/downloads" className="downloads-menu-item">Queue</Link>
                      <Link to="/downloads/history" className="downloads-menu-item">History</Link>
                      <Link to="/downloads/devices" className="downloads-menu-item">Devices</Link>
                    </div>
                  </div>
                )}
                <div className="account-menu" ref={accountMenuRef}>
                  <button
                    className="account-menu-trigger"
                    onClick={() => setAccountMenuOpen(!accountMenuOpen)}
                  >
                    {user?.username || 'Account'}
                  </button>
                  {accountMenuOpen && (
                    <div className="account-menu-dropdown">

                      <Link
                        to="/account"
                        className="account-menu-item"
                        onClick={() => setAccountMenuOpen(false)}
                      >
                        Account Settings
                      </Link>
                      <Link
                        to="/bugreports"
                        className="account-menu-item"
                        onClick={() => setAccountMenuOpen(false)}
                      >
                        Bug Reports
                      </Link>
                      {isAdmin && (
                        <>
                          <Link
                            to="/users-stats"
                            className="account-menu-item"
                            onClick={() => setAccountMenuOpen(false)}
                          >
                            Users Stats
                          </Link>
                          <Link
                            to="/current-transfers"
                            className="account-menu-item"
                            onClick={() => setAccountMenuOpen(false)}
                          >
                            Current Transfers
                          </Link>
                          <Link
                            to="/clients-stats"
                            className="account-menu-item"
                            onClick={() => setAccountMenuOpen(false)}
                          >
                            Clients Stats
                          </Link>
                          <Link
                            to="/media-validation"
                            className="account-menu-item"
                            onClick={() => setAccountMenuOpen(false)}
                          >
                            Medias Validation
                            {pendingMediaCount > 0 && (
                              <span className="nav-badge">{pendingMediaCount}</span>
                            )}
                          </Link>
                          <Link
                            to="/download-queues"
                            className="account-menu-item"
                            onClick={() => setAccountMenuOpen(false)}
                          >
                            Download Queues
                          </Link>
                          <Link
                            to="/downloads/history/all"
                            className="account-menu-item"
                            onClick={() => setAccountMenuOpen(false)}
                          >
                            Global History
                          </Link>
                          <Link
                            to="/playlist/top-systems"
                            className="account-menu-item"
                            onClick={() => setAccountMenuOpen(false)}
                          >
                            Top Systems Download
                          </Link>
                          <Link
                            to="/connected-clients"
                            className="account-menu-item"
                            onClick={() => setAccountMenuOpen(false)}
                          >
                            Connected Clients
                          </Link>
                          <Link
                            to="/systems-configuration"
                            className="account-menu-item"
                            onClick={() => setAccountMenuOpen(false)}
                          >
                            Systems Configuration
                          </Link>
                          <Link
                            to="/torrent-tracker-stats"
                            className="account-menu-item"
                            onClick={() => setAccountMenuOpen(false)}
                          >
                            Torrent Tracker Stats
                          </Link>
                          <Link
                            to="/debug"
                            className="account-menu-item"
                            onClick={() => setAccountMenuOpen(false)}
                          >
                            Debug
                          </Link>
                          <button
                            onClick={handleRefreshCatalog}
                            className="account-menu-item"
                            disabled={isRefreshing}
                          >
                            {isRefreshing ? 'Refreshing...' : 'Refresh Catalog'}
                          </button>
                        </>
                      )}
                      <button
                        onClick={handleLogout}
                        className="account-menu-item logout-item"
                      >
                        Logout
                      </button>
                    </div>
                  )}
                </div>
              </>
            ) : (
              <Link to="/login">Login</Link>
            )}
          </nav>
        </div>
      </header>
      <main className="main">
        <Outlet />
      </main>

      {showPendingModal && (
        <div className="pending-modal-overlay" onClick={handlePendingModalClose}>
          <div className="pending-modal" onClick={(e) => e.stopPropagation()}>
            <div className="pending-modal-header">
              <h2>Pending Media Validation</h2>
              <button className="pending-modal-close" onClick={handlePendingModalClose}>&times;</button>
            </div>
            <div className="pending-modal-body">
              <p>
                There {pendingMediaCount === 1 ? 'is' : 'are'} <strong>{pendingMediaCount}</strong> media file{pendingMediaCount !== 1 ? 's' : ''} waiting for validation.
              </p>
            </div>
            <div className="pending-modal-footer">
              <button className="pending-modal-btn-secondary" onClick={handlePendingModalClose}>Dismiss</button>
              <button className="pending-modal-btn-primary" onClick={handlePendingModalValidate}>Go to Medias Validation</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}



export default Layout

