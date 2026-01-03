import React from 'react'
import { Outlet, Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'
import HeaderSearch from './HeaderSearch'
import './Layout.css'

const Layout = () => {
  const { user, isAuthenticated, isCreator, logout } = useAuth()
  const navigate = useNavigate()

  const handleLogout = () => {
    logout()
  }

  return (
    <div className="layout">
      <header className="header">
        <div className="header-content">
          <Link to="/" className="logo">
            <h1>Batocera Games Catalog</h1>
          </Link>
          {isAuthenticated && <HeaderSearch />}
          <nav className="nav">
            {isAuthenticated ? (
              <>
                <Link to="/systems">Systems</Link>
                <Link to="/search">Search</Link>
                {isCreator && <Link to="/downloads">Downloads</Link>}
                <Link to="/account">Account</Link>
                <div className="user-info">
                  <span>{user?.username}</span>
                  <button onClick={handleLogout} className="logout-btn">Logout</button>
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

