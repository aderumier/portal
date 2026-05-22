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
  const [viewMode, setViewMode] = useState('grid')
  const [selectedHardware, setSelectedHardware] = useState(null)
  const [sortColumn, setSortColumn] = useState(() => localStorage.getItem('systemsSortColumn') || 'name')
  const [sortDirection, setSortDirection] = useState(() => localStorage.getItem('systemsSortDirection') || 'asc')
  const [searchQuery, setSearchQuery] = useState('')

  useEffect(() => {
    localStorage.setItem('systemsSortColumn', sortColumn)
    localStorage.setItem('systemsSortDirection', sortDirection)
  }, [sortColumn, sortDirection])

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

  const handleViewChange = (mode) => {
    setViewMode(mode)
    localStorage.setItem('systemsViewMode', mode)
  }

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

  // Group systems by hardware category (exclude library)
  const groupedSystems = systems.reduce((acc, system) => {
    const hardware = system.hardware || 'unknown'
    if (hardware.toLowerCase() === 'library') return acc
    if (!acc[hardware]) acc[hardware] = []
    acc[hardware].push(system)
    return acc
  }, {})

  const hardwareOrder = ['console', 'portable', 'computer', 'arcade', 'port', 'pcgaming', 'vintage', 'pinball', 'unknown']
  const sortedHardware = Object.keys(groupedSystems).sort((a, b) => {
    const aIndex = hardwareOrder.indexOf(a)
    const bIndex = hardwareOrder.indexOf(b)
    if (aIndex !== -1 && bIndex !== -1) return aIndex - bIndex
    if (aIndex !== -1) return -1
    if (bIndex !== -1) return 1
    return a.localeCompare(b)
  })

  const filteredHardware = selectedHardware
    ? sortedHardware.filter(h => h === selectedHardware)
    : sortedHardware

  const handleSort = React.useCallback((column) => {
    setSortColumn(prevColumn => {
      if (prevColumn === column) {
        setSortDirection(prevDir => prevDir === 'asc' ? 'desc' : 'asc')
        return column
      } else {
        setSortDirection('asc')
        return column
      }
    })
  }, [])

  const formatHardwareName = (hardware) => {
    return hardware.charAt(0).toUpperCase() + hardware.slice(1).replace(/([A-Z])/g, ' $1')
  }

  const extractVersionNumber = (version) => {
    if (!version) return null
    const match = version.match(/v?(\d+(?:\.\d+)?)/)
    return match ? match[1] : null
  }

  const formatReleaseDate = (dateString) => {
    if (!dateString || dateString === 'Unknown') return dateString
    const str = String(dateString)
    if (/^\d{8}/.test(str)) {
      const year = str.substring(0, 4)
      const month = str.substring(4, 6)
      const day = str.substring(6, 8)
      return `${day}-${month}-${year}`
    }
    const isoMatch = str.match(/^(\d{4})-(\d{2})-(\d{2})/)
    if (isoMatch) return `${isoMatch[3]}-${isoMatch[2]}-${isoMatch[1]}`
    const euroMatch = str.match(/^(\d{2})[/.-](\d{2})[/.-](\d{4})/)
    if (euroMatch) return `${euroMatch[1]}-${euroMatch[2]}-${euroMatch[3]}`
    return str
  }

  const compareSystemsByColumn = (a, b, column, direction) => {
    let compareResult = 0
    if (column === 'name') {
      compareResult = (a.name || '').localeCompare(b.name || '')
    } else if (column === 'manufacturer') {
      compareResult = (a.manufacturer || 'Unknown').toLowerCase().localeCompare((b.manufacturer || 'Unknown').toLowerCase())
    } else if (column === 'release') {
      const releaseA = a.release || 'Unknown'
      const releaseB = b.release || 'Unknown'
      const yearA = parseInt(releaseA)
      const yearB = parseInt(releaseB)
      if (!isNaN(yearA) && !isNaN(yearB)) compareResult = yearA - yearB
      else if (releaseA === 'Unknown') compareResult = 1
      else if (releaseB === 'Unknown') compareResult = -1
      else compareResult = releaseA.localeCompare(releaseB)
    } else if (column === 'gamelistDate') {
      const dateA = a.gamelistDate || ''
      const dateB = b.gamelistDate || ''
      if (!dateA && !dateB) compareResult = 0
      else if (!dateA) compareResult = 1
      else if (!dateB) compareResult = -1
      else {
        const parseDateString = (str) => {
          const parts = str.split(/[-/]/)
          if (parts.length === 3) return `${parts[2]}${parts[1].padStart(2, '0')}${parts[0].padStart(2, '0')}`
          return str
        }
        compareResult = parseDateString(dateA).localeCompare(parseDateString(dateB))
      }
    }
    return direction === 'desc' ? -compareResult : compareResult
  }

  const searchLower = searchQuery.toLowerCase().trim()

  // Table view: flat globally-sorted list
  const tableSystems = filteredHardware
    .flatMap(hw => groupedSystems[hw])
    .filter(s => !searchLower || (s.name || '').toLowerCase().includes(searchLower))
    .sort((a, b) => compareSystemsByColumn(a, b, sortColumn, sortDirection))

  // Grid view: sort within each group (default sort), then apply search filter
  const gridHardwareGroups = filteredHardware
    .map(hw => {
      const sorted = [...groupedSystems[hw]].sort((a, b) => {
        const manufacturerA = (a.manufacturer || 'Unknown').toLowerCase()
        const manufacturerB = (b.manufacturer || 'Unknown').toLowerCase()
        if (manufacturerA !== manufacturerB) return manufacturerA.localeCompare(manufacturerB)
        const releaseA = a.release || 'Unknown'
        const releaseB = b.release || 'Unknown'
        if (releaseA !== releaseB) {
          const yearA = parseInt(releaseA), yearB = parseInt(releaseB)
          if (!isNaN(yearA) && !isNaN(yearB)) return yearA - yearB
          if (!isNaN(yearA) && isNaN(yearB)) return -1
          if (isNaN(yearA) && !isNaN(yearB)) return 1
          if (releaseA === 'Unknown') return 1
          if (releaseB === 'Unknown') return -1
          return releaseA.localeCompare(releaseB)
        }
        return (a.name || '').toLowerCase().localeCompare((b.name || '').toLowerCase())
      })
      return {
        hardware: hw,
        systems: sorted.filter(s => !searchLower || (s.name || '').toLowerCase().includes(searchLower))
      }
    })
    .filter(g => g.systems.length > 0)

  return (
    <div className="systems-list">
      <div className="systems-header">
        <h1>Game Systems</h1>
        <div className="systems-header-controls">
          <div className="name-filter-container">
            <input
              type="text"
              className="name-filter-input"
              placeholder="Search systems..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
            />
          </div>
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
          {gridHardwareGroups.map(({ hardware, systems: groupSystems }) => (
            <div key={hardware} className="hardware-category">
              <h2 className="hardware-category-title">{formatHardwareName(hardware)}</h2>
              <div className="systems-grid">
                {groupSystems.map((system) => {
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
              {tableSystems.map((system) => {
                const systemImage = getSystemLogoUrl(system.id)
                return (
                  <tr key={system.id}>
                    <td className="system-image-cell">
                      <img
                        src={systemImage}
                        alt={system.name}
                        className="system-table-image"
                        onError={(e) => { e.target.style.display = 'none' }}
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
                      {catalogType === 'releases' && isAuthenticated && torrentSystems.has(system.id) && (
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
      )}
    </div>
  )
}

export default SystemsList
