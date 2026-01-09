import React, { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { useCatalog } from '../../context/CatalogContext'
import './SystemsList.css'

const SystemsList = ({ systems }) => {
  const { catalogType } = useCatalog()
  const [viewMode, setViewMode] = useState('grid') // 'grid' or 'table'
  const [selectedHardware, setSelectedHardware] = useState(null) // null = all, or specific hardware type

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

  // Group systems by hardware category (exclude library category)
  const groupedSystems = systems.reduce((acc, system) => {
    const hardware = system.hardware || 'unknown'
    // Skip library category
    if (hardware.toLowerCase() === 'library') {
      return acc
    }
    if (!acc[hardware]) {
      acc[hardware] = []
    }
    acc[hardware].push(system)
    return acc
  }, {})

  // Sort systems within each hardware category by manufacturer, then by release year, then by name
  Object.keys(groupedSystems).forEach(hardware => {
    groupedSystems[hardware].sort((a, b) => {
      // First sort by manufacturer
      const manufacturerA = (a.manufacturer || 'Unknown').toLowerCase()
      const manufacturerB = (b.manufacturer || 'Unknown').toLowerCase()
      if (manufacturerA !== manufacturerB) {
        return manufacturerA.localeCompare(manufacturerB)
      }
      // If same manufacturer, sort by release year (ascending, Unknown last)
      const releaseA = a.release || 'Unknown'
      const releaseB = b.release || 'Unknown'
      if (releaseA !== releaseB) {
        // If both are numeric years, compare as numbers
        const yearA = parseInt(releaseA)
        const yearB = parseInt(releaseB)
        if (!isNaN(yearA) && !isNaN(yearB)) {
          return yearA - yearB
        }
        // If one is numeric and the other is not, numeric comes first
        if (!isNaN(yearA) && isNaN(yearB)) return -1
        if (isNaN(yearA) && !isNaN(yearB)) return 1
        // Both are non-numeric, sort alphabetically (Unknown goes last)
        if (releaseA === 'Unknown') return 1
        if (releaseB === 'Unknown') return -1
        return releaseA.localeCompare(releaseB)
      }
      // If same manufacturer and release, sort by name
      const nameA = (a.name || '').toLowerCase()
      const nameB = (b.name || '').toLowerCase()
      return nameA.localeCompare(nameB)
    })
  })

  // Sort hardware categories (custom order, then alphabetically)
  const hardwareOrder = ['console', 'portable', 'computer', 'arcade', 'port', 'pcgaming', 'vintage', 'pinball', 'unknown']
  const sortedHardware = Object.keys(groupedSystems).sort((a, b) => {
    const aIndex = hardwareOrder.indexOf(a)
    const bIndex = hardwareOrder.indexOf(b)
    if (aIndex !== -1 && bIndex !== -1) return aIndex - bIndex
    if (aIndex !== -1) return -1
    if (bIndex !== -1) return 1
    return a.localeCompare(b)
  })

  // Filter hardware categories based on selection
  const filteredHardware = selectedHardware 
    ? sortedHardware.filter(h => h === selectedHardware)
    : sortedHardware

  // Format hardware name for display
  const formatHardwareName = (hardware) => {
    return hardware.charAt(0).toUpperCase() + hardware.slice(1).replace(/([A-Z])/g, ' $1')
  }

  // Get system image path using system ID directly (no suffix stripping)
  const getSystemImagePath = (systemId) => {
    return `/systems_logos/${systemId}.webp`
  }

  // Extract version number from version string (e.g., "v10.5" -> "10.5")
  const extractVersionNumber = (version) => {
    if (!version) return null
    // Match digits and dots after 'v' prefix (e.g., "v10.5" -> "10.5")
    const match = version.match(/v?(\d+(?:\.\d+)?)/)
    return match ? match[1] : null
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

      {/* Hardware Filter Bar */}
      <div className="hardware-filter-bar">
        <button
          className={`hardware-filter-btn ${selectedHardware === null ? 'active' : ''}`}
          onClick={() => setSelectedHardware(null)}
        >
          All
        </button>
        {sortedHardware.map((hardware) => (
          <button
            key={hardware}
            className={`hardware-filter-btn ${selectedHardware === hardware ? 'active' : ''}`}
            onClick={() => setSelectedHardware(hardware)}
          >
            {formatHardwareName(hardware)}
            <span className="hardware-count">({groupedSystems[hardware].length})</span>
          </button>
        ))}
      </div>

      {viewMode === 'grid' ? (
        <div className="systems-by-hardware">
          {filteredHardware.map((hardware) => (
            <div key={hardware} className="hardware-category">
              <h2 className="hardware-category-title">{formatHardwareName(hardware)}</h2>
              <div className="systems-grid">
                {groupedSystems[hardware].map((system) => {
                  const systemImage = getSystemImagePath(system.id)
                  return (
                    <Link 
                      key={system.id} 
                      to={`/system/${system.id}`}
                      className="system-card"
                    >
                      <div className="system-card-image">
                        <img 
                          src={systemImage} 
                          alt={system.name}
                          onError={(e) => {
                            // Fallback to a placeholder if image doesn't exist
                            e.target.style.display = 'none'
                          }}
                        />
                      </div>
                      <div className="system-card-content">
                        <h2>{system.name}</h2>
                        {catalogType === 'releases' && system.version && extractVersionNumber(system.version) && (
                          <p className="system-version-text">version {extractVersionNumber(system.version)}</p>
                        )}
                        <p>{system.gameCount} games</p>
                      </div>
                    </Link>
                  )
                })}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="systems-by-hardware">
          {filteredHardware.map((hardware) => (
            <div key={hardware} className="hardware-category">
              <h2 className="hardware-category-title">{formatHardwareName(hardware)}</h2>
              <div className="systems-table-container">
                <table className="systems-table">
                  <thead>
                    <tr>
                      <th>Image</th>
                      <th>System Name</th>
                      <th>Games</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {groupedSystems[hardware].map((system) => {
                      const systemImage = getSystemImagePath(system.id)
                      return (
                        <tr key={system.id}>
                          <td className="system-image-cell">
                            <img 
                              src={systemImage} 
                              alt={system.name}
                              className="system-table-image"
                              onError={(e) => {
                                // Hide image if it doesn't exist
                                e.target.style.display = 'none'
                              }}
                            />
                          </td>
                          <td className="system-name-cell">
                            <Link to={`/system/${system.id}`} className="system-link">
                              {system.name}
                            </Link>
                            {catalogType === 'releases' && system.version && extractVersionNumber(system.version) && (
                              <div className="system-version-text">version {extractVersionNumber(system.version)}</div>
                            )}
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
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default SystemsList

