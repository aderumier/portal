import React, { useState, useEffect, useCallback } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'
import { getMediaUrl, getThumbnailUrl } from '../../utils/constants'
import { getContributeGames } from '../../api/catalog'
import MediaUpload from '../Media/MediaUpload'
import './SystemGames.css'
import './ContributeGamesList.css'

const VideoIcon = () => (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" title="Video available">
    <rect x="2" y="5" width="15" height="14" rx="2" stroke="currentColor" strokeWidth="1.5" fill="none" />
    <path d="M17 9l5-3v12l-5-3V9z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" fill="none" />
  </svg>
)

const ContributeGamesList = ({ systemId }) => {
  const [allGames, setAllGames] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [systemName, setSystemName] = useState('')
  const [selectedLetter, setSelectedLetter] = useState(null)
  const [nameFilter, setNameFilter] = useState('')
  const [sortColumn, setSortColumn] = useState('name')
  const [sortDirection, setSortDirection] = useState('asc')
  const { isAdmin } = useAuth()
  const navigate = useNavigate()

  const loadGames = useCallback(async () => {
    try {
      setLoading(true)
      const response = await getContributeGames(systemId)
      const games = response.games || []
      setAllGames(games)
      if (games.length > 0) {
        setSystemName(games[0].systemName || systemId)
      }
    } catch (err) {
      console.error('Error loading contribute games:', err)
      setError('Failed to load games')
    } finally {
      setLoading(false)
    }
  }, [systemId])

  useEffect(() => {
    loadGames()
  }, [loadGames])

  const letters = ['#', ...Array.from({ length: 26 }, (_, i) => String.fromCharCode(65 + i))]

  const formatReleaseYear = (dateString) => {
    if (!dateString) return null
    const str = String(dateString)
    if (/^\d{8}/.test(str)) return str.substring(0, 4)
    const match = str.match(/^(\d{4})/)
    return match ? match[1] : null
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

  const handleGameClick = (game) => {
    let gameId = game.id.replace(/^\.\//, '')
    if (gameId.startsWith(`${game.system}/`)) {
      gameId = gameId.substring(game.system.length + 1)
    }
    navigate(`/game/${game.system}/${encodeURIComponent(gameId)}`, {
      state: { catalogType: 'wip' }
    })
  }

  const filteredGames = allGames
    .filter(game => {
      if (selectedLetter) {
        const firstChar = (game.name || '').trim()[0] || ''
        if (selectedLetter === '#') {
          if (/[A-Za-z]/.test(firstChar)) return false
        } else {
          if (firstChar.toUpperCase() !== selectedLetter) return false
        }
      }
      if (nameFilter) {
        if (!(game.name || '').toLowerCase().includes(nameFilter.toLowerCase())) return false
      }
      return true
    })
    .sort((a, b) => {
      let cmp = 0
      if (sortColumn === 'name') {
        cmp = (a.name || '').localeCompare(b.name || '')
      } else if (sortColumn === 'publisher') {
        cmp = (a.publisher || '').localeCompare(b.publisher || '')
      } else if (sortColumn === 'releaseDate') {
        cmp = (formatReleaseYear(a.releasedate) || '0').localeCompare(formatReleaseYear(b.releasedate) || '0')
      }
      return sortDirection === 'desc' ? -cmp : cmp
    })

  const SortHeader = ({ column, label }) => (
    <th className="sortable" onClick={() => handleSort(column)} style={{ cursor: 'pointer' }}>
      {label} {sortColumn === column && (sortDirection === 'asc' ? '↑' : '↓')}
    </th>
  )

  const MediaCell = ({ game, field, label }) => {
    const path = game[field]
    const canUpload = isAdmin && (field === 'fanart' || field === 'marquee')

    if (path) {
      const url = getThumbnailUrl(path, 80, 60) || getMediaUrl(path)
      return (
        <td className="contribute-media-cell">
          <img src={url} alt={label} className="contribute-media-thumb" loading="lazy" />
        </td>
      )
    }

    if (canUpload) {
      return (
        <td className="contribute-media-cell contribute-media-missing">
          <MediaUpload
            system={game.system}
            gameId={game.id}
            mediaType={field}
            label={label}
            onUploadSuccess={loadGames}
            compact={true}
          />
        </td>
      )
    }

    return <td className="contribute-media-cell contribute-media-missing"><span className="media-none">-</span></td>
  }

  const VideoCell = ({ game }) => {
    if (game.video) {
      return (
        <td className="contribute-media-cell">
          <span className="contribute-video-icon" title="Video available"><VideoIcon /></span>
        </td>
      )
    }
    return <td className="contribute-media-cell contribute-media-missing"><span className="media-none">-</span></td>
  }

  if (loading && allGames.length === 0) {
    return <div className="loading">Loading games...</div>
  }

  if (error && allGames.length === 0) {
    return <div className="error">{error}</div>
  }

  return (
    <div className="system-games">
      <div className="system-games-header">
        <div className="system-games-title-section">
          <div className="contribute-breadcrumb">
            <Link to="/contribute" className="contribute-back-link">← Contribute</Link>
          </div>
          <h1>{systemName} — Missing Medias</h1>
          <div className="name-filter-container">
            <input
              type="text"
              className="name-filter-input"
              placeholder="Filter by name..."
              value={nameFilter}
              onChange={(e) => setNameFilter(e.target.value)}
            />
          </div>
        </div>
      </div>

      <div className="filters-container">
        <div className="letter-filter-bar">
          <button
            className={`letter-filter-btn ${selectedLetter === null ? 'active' : ''}`}
            onClick={() => setSelectedLetter(null)}
          >
            All
          </button>
          {letters.map((letter) => (
            <button
              key={letter}
              className={`letter-filter-btn ${selectedLetter === letter ? 'active' : ''}`}
              onClick={() => setSelectedLetter(letter)}
            >
              {letter}
            </button>
          ))}
        </div>
      </div>

      {filteredGames.length === 0 ? (
        <div className="no-games">No games found with missing medias</div>
      ) : (
        <div className="games-table-container">
          <table className="games-table contribute-games-table">
            <thead>
              <tr>
                <th>Image</th>
                <SortHeader column="name" label="Game Name" />
                <SortHeader column="publisher" label="Publisher" />
                <SortHeader column="releaseDate" label="Year" />
                <th>Fanart</th>
                <th>Marquee</th>
                <th>Video</th>
              </tr>
            </thead>
            <tbody>
              {filteredGames.map((game) => {
                const bestImage = game.catalog_image || game.image
                const imageUrl = bestImage ? getMediaUrl(bestImage) : '/assets/images/no-image.png'

                return (
                  <tr
                    key={game.id}
                    onClick={() => handleGameClick(game)}
                    className="game-table-row"
                  >
                    <td className="game-image-cell">
                      <img
                        src={imageUrl}
                        alt={game.name}
                        className="table-game-image"
                        loading="lazy"
                      />
                    </td>
                    <td className="game-name-cell">
                      <span className="game-name">{game.name}</span>
                    </td>
                    <td className="game-publisher-cell">
                      {game.publisher || '-'}
                    </td>
                    <td className="game-releaseyear-cell">
                      {formatReleaseYear(game.releasedate) || '-'}
                    </td>
                    <td className="contribute-media-cell" onClick={(e) => e.stopPropagation()}>
                      {game.fanart ? (
                        <img
                          src={getThumbnailUrl(game.fanart, 80, 60) || getMediaUrl(game.fanart)}
                          alt="fanart"
                          className="contribute-media-thumb"
                          loading="lazy"
                        />
                      ) : isAdmin ? (
                        <MediaUpload
                          system={game.system}
                          gameId={game.id}
                          mediaType="fanart"
                          label="Fanart"
                          onUploadSuccess={loadGames}
                          compact={true}
                        />
                      ) : (
                        <span className="media-none">-</span>
                      )}
                    </td>
                    <td className="contribute-media-cell" onClick={(e) => e.stopPropagation()}>
                      {game.marquee ? (
                        <img
                          src={getThumbnailUrl(game.marquee, 80, 60) || getMediaUrl(game.marquee)}
                          alt="marquee"
                          className="contribute-media-thumb"
                          loading="lazy"
                        />
                      ) : isAdmin ? (
                        <MediaUpload
                          system={game.system}
                          gameId={game.id}
                          mediaType="marquee"
                          label="Marquee"
                          onUploadSuccess={loadGames}
                          compact={true}
                        />
                      ) : (
                        <span className="media-none">-</span>
                      )}
                    </td>
                    <td className="contribute-media-cell" onClick={(e) => e.stopPropagation()}>
                      {game.video ? (
                        <span className="contribute-video-icon" title="Video available"><VideoIcon /></span>
                      ) : (
                        <span className="media-none">-</span>
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

export default ContributeGamesList
