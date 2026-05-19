import React, { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { useCatalog } from '../../context/CatalogContext'
import { useAuth } from '../../context/AuthContext'
import { getSystemLogoUrl } from '../../utils/constants'
import client from '../../api/client'
import './SystemsList.css'

const TorrentIcon = () => (
  <img src="/qbittorrent-icon.svg" width="22" height="22" alt="torrent" style={{ display: 'block' }} />
)

const SystemsList = ({ systems }) => {
  const { catalogType } = useCatalog()
  const { isAuthenticated } = useAuth()
  const [torrentSystems, setTorrentSystems] = useState(new Set())
  const [viewMode, setViewMode] = useState('grid') // 'grid' or 'table'
  const [selectedHardware, setSelectedHardware] = useState(null) // null = all, or specific hardware type
  const [sortColumn, setSortColumn] = useState(() => localStorage.getItem('systemsSortColumn') || 'name') // 'name', 'manufacturer', 'release'
  const [sortDirection, setSortDirection] = useState(() => localStorage.getItem('systemsSortDirection') || 'asc') // 'asc' or 'desc'

  // Persist sort preferences to localStorage
  useEffect(() => {
    localStorage.setItem('systemsSortColumn', sortColumn)
    localStorage.setItem('systemsSortDirection', sortDirection)
  }, [sortColumn, sortDirection])

  // Load view preference and hardware filter from localStorage
  useEffect(() => {
    const savedView = localStorage.getItem('systemsViewMode')
    if (savedView === 'table' || savedView === 'grid') {
      setViewMode(savedView)
    }

    const savedHardware = localStorage.getItem('systemsHardwareFilter')
    if (savedHardware !== null) {
      setSelectedHardware(savedHardware === 'all' ? null : savedHardware)
    }
  }, [])

  // Save view preference to localStorage
  const handleViewChange = (mode) => {
    setViewMode(mode)
    localStorage.setItem('systemsViewMode', mode)
  }

  // Save hardware filter to localStorage
  const handleHardwareChange = (hardware) => {
    setSelectedHardware(hardware)
    localStorage.setItem('systemsHardwareFilter', hardware === null ? 'all' : hardware)
  }

  useEffect(() => {
    if (!isAuthenticated) return
    client.get('/api/catalog/torrent-systems')
      .then(r => setTorrentSystems(new Set(r.data.system_ids)))
      .catch(() => {})
  }, [isAuthenticated])

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

  // Sort systems within each hardware category
  // In table view, use the selected sort column/direction
  // In grid view, use default sorting (manufacturer, then release, then name)
  Object.keys(groupedSystems).forEach(hardware => {
    groupedSystems[hardware].sort((a, b) => {
      if (viewMode === 'table' && sortColumn) {
        // Table view: use selected sort column
        let compareResult = 0

        if (sortColumn === 'name') {
          compareResult = (a.name || '').localeCompare(b.name || '')
        } else if (sortColumn === 'manufacturer') {
          const manufacturerA = (a.manufacturer || 'Unknown').toLowerCase()
          const manufacturerB = (b.manufacturer || 'Unknown').toLowerCase()
          compareResult = manufacturerA.localeCompare(manufacturerB)
        } else if (sortColumn === 'release') {
          const releaseA = a.release || 'Unknown'
          const releaseB = b.release || 'Unknown'
          // Try to parse as numbers first
          const yearA = parseInt(releaseA)
          const yearB = parseInt(releaseB)
          if (!isNaN(yearA) && !isNaN(yearB)) {
            compareResult = yearA - yearB
          } else {
            // If one is Unknown, Unknown goes last
            if (releaseA === 'Unknown') compareResult = 1
            else if (releaseB === 'Unknown') compareResult = -1
            else compareResult = releaseA.localeCompare(releaseB)
          }
        } else if (sortColumn === 'gamelistDate') {
          const dateA = a.gamelistDate || ''
          const dateB = b.gamelistDate || ''

          if (!dateA && !dateB) compareResult = 0
          else if (!dateA) compareResult = 1 // Empty dates go last
          else if (!dateB) compareResult = -1
          else {
            // Parse dd-mm-yyyy or similar formats for proper date sorting
            // Convert to YYYYMMDD for easier comparison
            const parseDateString = (str) => {
              const parts = str.split(/[-/]/)
              if (parts.length === 3) {
                // Assuming DD-MM-YYYY
                return `${parts[2]}${parts[1].padStart(2, '0')}${parts[0].padStart(2, '0')}`
              }
              return str
            }

            const strA = parseDateString(dateA)
            const strB = parseDateString(dateB)

            compareResult = strA.localeCompare(strB)
          }
        }

        // Apply sort direction
        return sortDirection === 'desc' ? -compareResult : compareResult
      } else {
        // Grid view: default sorting (manufacturer, then release, then name)
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
      }
    })
  })

  // handleSort must be defined before using it in JSX
  const handleSort = React.useCallback((column) => {
    setSortColumn(prevColumn => {
      if (prevColumn === column) {
        // Toggle direction if clicking the same column
        setSortDirection(prevDir => prevDir === 'asc' ? 'desc' : 'asc')
        return column
      } else {
        // New column, default to ascending
        setSortDirection('asc')
        return column
      }
    })
  }, [])

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


  // Extract version number from version string (e.g., "v10.5" -> "10.5")
  const extractVersionNumber = (version) => {
    if (!version) return null
    // Match digits and dots after 'v' prefix (e.g., "v10.5" -> "10.5")
    const match = version.match(/v?(\d+(?:\.\d+)?)/)
    return match ? match[1] : null
  }

  // Format release date to dd-mm-yyyy
  const formatReleaseDate = (dateString) => {
    if (!dateString || dateString === 'Unknown') return dateString;

    const str = String(dateString);

    // Format YYYYMMDD... or YYYYMMDDTHHMMSS (EmulationStation format)
    if (/^\d{8}/.test(str)) {
      const year = str.substring(0, 4);
      const month = str.substring(4, 6);
      const day = str.substring(6, 8);
      return `${day}-${month}-${year}`;
    }

    // Format YYYY-MM-DD
    const isoMatch = str.match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (isoMatch) {
      return `${isoMatch[3]}-${isoMatch[2]}-${isoMatch[1]}`;
    }

    // Format DD/MM/YYYY or DD-MM-YYYY
    const euroMatch = str.match(/^(\d{2})[/.-](\d{2})[/.-](\d{4})/);
    if (euroMatch) {
      return `${euroMatch[1]}-${euroMatch[2]}-${euroMatch[3]}`;
    }

    return str;
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
              <rect x="2" y="2" width="6" height="6" rx="1" stroke="currentColor" strokeWidth="1.5" fill="none" />
              <rect x="12" y="2" width="6" height="6" rx="1" stroke="currentColor" strokeWidth="1.5" fill="none" />
              <rect x="2" y="12" width="6" height="6" rx="1" stroke="currentColor" strokeWidth="1.5" fill="none" />
              <rect x="12" y="12" width="6" height="6" rx="1" stroke="currentColor" strokeWidth="1.5" fill="none" />
            </svg>
          </button>
          <button
            className={`view-toggle-btn ${viewMode === 'table' ? 'active' : ''}`}
            onClick={() => handleViewChange('table')}
            title="Table View"
            aria-label="Table View"
          >
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M2 4H18M2 8H18M2 12H18M2 16H18" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              <path d="M2 4V16M6 4V16M10 4V16M14 4V16M18 4V16" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
          </button>
        </div>
      </div>

      {/* Hardware Filter Bar */}
      <div className="hardware-filter-bar">
        <button
          className={`hardware-filter-btn ${selectedHardware === null ? 'active' : ''}`}
          onClick={() => handleHardwareChange(null)}
        >
          All
        </button>
        {sortedHardware.map((hardware) => (
          <button
            key={hardware}
            className={`hardware-filter-btn ${selectedHardware === hardware ? 'active' : ''}`}
            onClick={() => handleHardwareChange(hardware)}
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
                  const systemImage = getSystemLogoUrl(system.id)
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
                          onError={(e) => { e.target.style.display = 'none' }}
                        />
                      </div>
                      <div className="system-card-content">
                        <h2>{system.name}</h2>
                        {catalogType === 'releases' && system.version && extractVersionNumber(system.version) && (
                          <p className="system-version-text">
                            {isAuthenticated && torrentSystems.has(system.id) ? (
                              <a
                                href={`/api/catalog/systems/${system.id}/torrent`}
                                className="system-version-torrent"
                                title="Download torrent"
                                onClick={(e) => e.stopPropagation()}
                              >
                                <TorrentIcon />
                                <span className="system-version-label">version {extractVersionNumber(system.version)}</span>
                              </a>
                            ) : (
                              <>version {extractVersionNumber(system.version)}</>
                            )}
                          </p>
                        )}
                        {system.gamelistDate && (
                          <p className="system-version-text">{system.gamelistDate}</p>
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
                      <th
                        className="sortable"
                        onClick={() => handleSort('name')}
                        style={{ cursor: 'pointer' }}
                      >
                        System Name {sortColumn === 'name' && (sortDirection === 'asc' ? '↑' : '↓')}
                      </th>
                      <th
                        className="sortable"
                        onClick={() => handleSort('release')}
                        style={{ cursor: 'pointer' }}
                      >
                        Release {sortColumn === 'release' && (sortDirection === 'asc' ? '↑' : '↓')}
                      </th>
                      <th
                        className="sortable"
                        onClick={() => handleSort('manufacturer')}
                        style={{ cursor: 'pointer' }}
                      >
                        Manufacturer {sortColumn === 'manufacturer' && (sortDirection === 'asc' ? '↑' : '↓')}
                      </th>
                      <th>Games</th>
                      <th
                        className="sortable"
                        onClick={() => handleSort('gamelistDate')}
                        style={{ cursor: 'pointer' }}
                      >
                        Last Update {sortColumn === 'gamelistDate' && (sortDirection === 'asc' ? '↑' : '↓')}
                      </th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {groupedSystems[hardware].map((system) => {
                      const systemImage = getSystemLogoUrl(system.id)
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
                          <td className="system-release-cell">
                            {system.release ? formatReleaseDate(system.release) : 'Unknown'}
                          </td>
                          <td className="system-manufacturer-cell">
                            {system.manufacturer || 'Unknown'}
                          </td>
                          <td className="system-games-cell">
                            <span className="games-count">{system.gameCount} games</span>
                          </td>
                          <td className="system-update-cell">
                            {system.gamelistDate || 'Unknown'}
                          </td>
                          <td className="system-actions-cell">
                            <Link
                              to={`/system/${system.id}`}
                              className="view-system-btn"
                            >
                              View Games
                            </Link>
                            {isAuthenticated && torrentSystems.has(system.id) && (
                              <a
                                href={`/api/catalog/systems/${system.id}/torrent`}
                                className="torrent-icon-btn"
                                title="Download torrent"
                              >
                                <TorrentIcon />
                              </a>
                            )}
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

