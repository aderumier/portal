import React, { useState } from 'react'
import { Link } from 'react-router-dom'
import { getSystemLogoUrl } from '../../utils/constants'
import './SystemsList.css'

const ContributeSystemsList = ({ systems }) => {
  const [sortColumn, setSortColumn] = useState('missingMediaCount')
  const [sortDirection, setSortDirection] = useState('desc')
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedHardware, setSelectedHardware] = useState(null)

  const hardwareOrder = ['console', 'portable', 'computer', 'arcade', 'port', 'pcgaming', 'vintage', 'pinball', 'unknown']

  const formatHardwareName = (hardware) => {
    return hardware.charAt(0).toUpperCase() + hardware.slice(1).replace(/([A-Z])/g, ' $1')
  }

  const handleSort = (column) => {
    setSortColumn(prev => {
      if (prev === column) {
        setSortDirection(dir => dir === 'asc' ? 'desc' : 'asc')
        return column
      }
      setSortDirection('asc')
      return column
    })
  }

  const formatReleaseDate = (dateString) => {
    if (!dateString || dateString === 'Unknown') return dateString
    const str = String(dateString)
    if (/^\d{8}/.test(str)) {
      return `${str.substring(6, 8)}-${str.substring(4, 6)}-${str.substring(0, 4)}`
    }
    const isoMatch = str.match(/^(\d{4})-(\d{2})-(\d{2})/)
    if (isoMatch) return `${isoMatch[3]}-${isoMatch[2]}-${isoMatch[1]}`
    return str
  }

  // Collect hardware types present in this systems list
  const hardwareSet = new Set(systems.map(s => s.hardware || 'unknown'))
  const sortedHardware = hardwareOrder.filter(h => hardwareSet.has(h))
  const extraHardware = [...hardwareSet].filter(h => !hardwareOrder.includes(h)).sort()
  const allHardware = [...sortedHardware, ...extraHardware]

  const searchLower = searchQuery.toLowerCase().trim()

  const filteredSystems = systems
    .filter(s => !selectedHardware || (s.hardware || 'unknown') === selectedHardware)
    .filter(s => !searchLower || (s.name || '').toLowerCase().includes(searchLower))
    .sort((a, b) => {
      let cmp = 0
      if (sortColumn === 'name') {
        cmp = (a.name || '').localeCompare(b.name || '')
      } else if (sortColumn === 'manufacturer') {
        cmp = (a.manufacturer || 'Unknown').toLowerCase().localeCompare((b.manufacturer || 'Unknown').toLowerCase())
      } else if (sortColumn === 'release') {
        const yearA = parseInt(a.release || '0')
        const yearB = parseInt(b.release || '0')
        cmp = isNaN(yearA) ? 1 : isNaN(yearB) ? -1 : yearA - yearB
      } else if (sortColumn === 'missingMediaCount') {
        cmp = (a.missingMediaCount || 0) - (b.missingMediaCount || 0)
      } else if (sortColumn === 'gamelistDate') {
        const da = a.gamelistDate || ''
        const db = b.gamelistDate || ''
        if (!da && !db) cmp = 0
        else if (!da) cmp = 1
        else if (!db) cmp = -1
        else {
          const norm = (s) => {
            const p = s.split(/[-/]/)
            return p.length === 3 ? `${p[2]}${p[1].padStart(2,'0')}${p[0].padStart(2,'0')}` : s
          }
          cmp = norm(da).localeCompare(norm(db))
        }
      }
      return sortDirection === 'desc' ? -cmp : cmp
    })

  const SortHeader = ({ column, label }) => (
    <th className="sortable" onClick={() => handleSort(column)} style={{ cursor: 'pointer' }}>
      {label} {sortColumn === column && (sortDirection === 'asc' ? '↑' : '↓')}
    </th>
  )

  return (
    <div className="systems-list">
      <div className="systems-header">
        <h1>Games Systems with missing medias</h1>
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
        </div>
      </div>

      <div className="hardware-filter-bar">
        <button
          className={`hardware-filter-btn ${selectedHardware === null ? 'active' : ''}`}
          onClick={() => setSelectedHardware(null)}
        >
          All
        </button>
        {allHardware.map(hw => (
          <button
            key={hw}
            className={`hardware-filter-btn ${selectedHardware === hw ? 'active' : ''}`}
            onClick={() => setSelectedHardware(hw)}
          >
            {formatHardwareName(hw)}
            <span className="hardware-count">
              ({systems.filter(s => (s.hardware || 'unknown') === hw).length})
            </span>
          </button>
        ))}
      </div>

      <div className="systems-table-container">
        <table className="systems-table">
          <thead>
            <tr>
              <th>Image</th>
              <SortHeader column="name" label="System Name" />
              <SortHeader column="release" label="Release" />
              <SortHeader column="manufacturer" label="Manufacturer" />
              <SortHeader column="missingMediaCount" label="Missing Media Games" />
              <SortHeader column="gamelistDate" label="Last Update" />
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {filteredSystems.map((system) => (
              <tr key={system.id}>
                <td className="system-image-cell">
                  <img
                    src={getSystemLogoUrl(system.id)}
                    alt={system.name}
                    className="system-table-image"
                    onError={(e) => { e.target.style.display = 'none' }}
                  />
                </td>
                <td className="system-name-cell">
                  <Link to={`/contribute/system/${system.id}`} className="system-link">
                    {system.name}
                  </Link>
                </td>
                <td className="system-release-cell">
                  {system.release ? formatReleaseDate(system.release) : 'Unknown'}
                </td>
                <td className="system-manufacturer-cell">
                  {system.manufacturer || 'Unknown'}
                </td>
                <td className="system-games-cell">
                  <span className="games-count">{system.missingMediaCount} games</span>
                </td>
                <td className="system-update-cell">
                  {system.gamelistDate || 'Unknown'}
                </td>
                <td className="system-actions-cell">
                  <Link to={`/contribute/system/${system.id}`} className="view-system-btn">
                    View Games
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default ContributeSystemsList
