import React, { useState, useRef, useEffect } from 'react'
import { Outlet, Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'
import HeaderSearch from './HeaderSearch'
import { refreshCatalog } from '../../api/catalog'
import './Layout.css'

const Layout = () => {
  const { user, isAuthenticated, isAdmin, isDownload, isFastDownload, logout } = useAuth()
  const navigate = useNavigate()
  const [accountMenuOpen, setAccountMenuOpen] = useState(false)
  const accountMenuRef = useRef(null)
  const [isRefreshing, setIsRefreshing] = useState(false)

  const handleLogout = () => {
    logout()
    setAccountMenuOpen(false)
  }

  const handleRefreshCatalog = async () => {
    setIsRefreshing(true)
    try {
      const result = await refreshCatalog()
      alert(`Catalog refreshed successfully!\nSystems: ${result.systems_count}\nTotal games: ${result.total_games}`)
      setAccountMenuOpen(false)
    } catch (error) {
      console.error('Error refreshing catalog:', error)
      alert('Failed to refresh catalog. Please try again.')
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
    }

    if (accountMenuOpen) {
      document.addEventListener('mousedown', handleClickOutside)
    }

    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
    }
  }, [accountMenuOpen])

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
                <Link to="/systems">Systems</Link>
                {(isDownload || isFastDownload) && (
                  <Link to="/downloads">Downloads</Link>
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
                            to="/media-validation" 
                            className="account-menu-item"
                            onClick={() => setAccountMenuOpen(false)}
                          >
                            Medias Validation
                          </Link>
                          <Link 
                            to="/download-queues" 
                            className="account-menu-item"
                            onClick={() => setAccountMenuOpen(false)}
                          >
                            Download Queues
                          </Link>
                          <Link 
                            to="/systems-configuration" 
                            className="account-menu-item"
                            onClick={() => setAccountMenuOpen(false)}
                          >
                            Systems Configuration
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
    </div>
  )
}

export default Layout

