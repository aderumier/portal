import React, { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import './SystemsList.css'

const SystemsList = ({ systems }) => {
  const [viewMode, setViewMode] = useState('grid') // 'grid' or 'table'

  // Load view preference from localStorage
  useEffect(() => {
    const savedView = localStorage.getItem('systemsViewMode')
    if (savedView === 'table' || savedView === 'grid') {
      setViewMode(savedView)
    }
  }, [])

  // Save view preference to localStorage
  const handleViewChange = (mode) => {
    setViewMode(mode)
    localStorage.setItem('systemsViewMode', mode)
  }

  return (
    <div className="systems-list">
      <div className="systems-header">
        <h1>Game Systems</h1>
        <div className="view-toggle">
          <button
            className={`view-toggle-btn ${viewMode === 'grid' ? 'active' : ''}`}
            onClick={() => handleViewChange('grid')}
            title="Grid View"
            aria-label="Grid View"
          >
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
              <rect x="2" y="2" width="6" height="6" rx="1" stroke="currentColor" strokeWidth="1.5" fill="none"/>
              <rect x="12" y="2" width="6" height="6" rx="1" stroke="currentColor" strokeWidth="1.5" fill="none"/>
              <rect x="2" y="12" width="6" height="6" rx="1" stroke="currentColor" strokeWidth="1.5" fill="none"/>
              <rect x="12" y="12" width="6" height="6" rx="1" stroke="currentColor" strokeWidth="1.5" fill="none"/>
            </svg>
          </button>
          <button
            className={`view-toggle-btn ${viewMode === 'table' ? 'active' : ''}`}
            onClick={() => handleViewChange('table')}
            title="Table View"
            aria-label="Table View"
          >
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M2 4H18M2 8H18M2 12H18M2 16H18" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
              <path d="M2 4V16M6 4V16M10 4V16M14 4V16M18 4V16" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
            </svg>
          </button>
        </div>
      </div>

      {viewMode === 'grid' ? (
        <div className="systems-grid">
          {systems.map((system) => (
            <Link 
              key={system.id} 
              to={`/system/${system.id}`}
              className="system-card"
            >
              <div className="system-card-content">
                <h2>{system.name}</h2>
                <p>{system.gameCount} games</p>
              </div>
            </Link>
          ))}
        </div>
      ) : (
        <div className="systems-table-container">
          <table className="systems-table">
            <thead>
              <tr>
                <th>System Name</th>
                <th>Games</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {systems.map((system) => (
                <tr key={system.id}>
                  <td className="system-name-cell">
                    <Link to={`/system/${system.id}`} className="system-link">
                      {system.name}
                    </Link>
                  </td>
                  <td className="system-games-cell">
                    <span className="games-count">{system.gameCount} games</span>
                  </td>
                  <td className="system-actions-cell">
                    <Link 
                      to={`/system/${system.id}`}
                      className="view-system-btn"
                    >
                      View Games
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

export default SystemsList

