import React, { useState, useRef, useEffect } from 'react'
import { Outlet, Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'
import HeaderSearch from './HeaderSearch'
import './Layout.css'

const Layout = () => {
  const { user, isAuthenticated, isAdmin, logout } = useAuth()
  const navigate = useNavigate()
  const [accountMenuOpen, setAccountMenuOpen] = useState(false)
  const accountMenuRef = useRef(null)

  const handleLogout = () => {
    logout()
    setAccountMenuOpen(false)
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
                <Link to="/downloads">Downloads</Link>
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

