import React, { useState, useEffect, useCallback, useRef } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'
import { getMediaUrl } from '../../utils/constants'
import { getContributeGames } from '../../api/catalog'
import client from '../../api/client'
import './SystemGames.css'
import './ContributeGamesList.css'

const VideoIcon = () => (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
    <rect x="2" y="5" width="15" height="14" rx="2" stroke="currentColor" strokeWidth="1.5" fill="none" />
    <path d="M17 9l5-3v12l-5-3V9z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" fill="none" />
  </svg>
)

const ImagePlaceholderIcon = () => (
  <svg width="30" height="24" viewBox="0 0 30 24" fill="none" xmlns="http://www.w3.org/2000/svg">
    <rect x="1" y="1" width="28" height="22" rx="2" stroke="currentColor" strokeWidth="1.5" fill="none" />
    <circle cx="8" cy="7" r="2.5" stroke="currentColor" strokeWidth="1.5" fill="none" />
    <path d="M1 17l7-7 5 5 4-4 12 9" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" fill="none" />
  </svg>
)

const UploadArrowIcon = () => (
  <svg width="14" height="14" viewBox="0 0 14 14" fill="none" xmlns="http://www.w3.org/2000/svg">
    <path d="M7 10V3M4 6l3-3 3 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M2 12h10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
  </svg>
)

const Lightbox = ({ url, alt, onClose }) => {
  useEffect(() => {
    const handleKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [onClose])

  return (
    <div className="lightbox-overlay" onClick={onClose}>
      <img
        src={url}
        alt={alt}
        className="lightbox-image"
        onClick={(e) => e.stopPropagation()}
      />
      <button className="lightbox-close" onClick={onClose}>✕</button>
    </div>
  )
}

const UploadPlaceholder = ({ system, gameId, mediaType, label, onUploadSuccess }) => {
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState(null)
  const [success, setSuccess] = useState(false)
  const fileInputRef = useRef(null)

  const uploadFile = async (file) => {
    const allowedTypes = ['image/png', 'image/jpeg', 'image/jpg', 'image/gif', 'image/webp']
    if (!allowedTypes.includes(file.type)) { setError('Invalid type'); return }
    if (file.size > 10 * 1024 * 1024) { setError('Too large'); return }
    setUploading(true)
    setError(null)
    try {
      const formData = new FormData()
      formData.append('file', file)
      formData.append('system', system)
      formData.append('game_id', gameId)
      formData.append('media_type', mediaType)
      const response = await client.post('/api/media/upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      if (response.data.success) { setSuccess(true); onUploadSuccess?.() }
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed')
    } finally {
      setUploading(false)
    }
  }

  const handleChange = (e) => {
    const file = e.target.files?.[0]
    if (file) uploadFile(file)
    e.target.value = ''
  }

  return (
    <div
      className={`contribute-upload-placeholder${uploading ? ' uploading' : ''}${success ? ' upload-success' : ''}`}
      onClick={() => !uploading && fileInputRef.current?.click()}
      title={`Upload ${label}`}
    >
      {success ? (
        <span className="placeholder-success-mark">✓</span>
      ) : uploading ? (
        <span className="placeholder-loading">…</span>
      ) : (
        <><ImagePlaceholderIcon /><UploadArrowIcon /></>
      )}
      {error && <span className="placeholder-error">{error}</span>}
      <input
        ref={fileInputRef}
        type="file"
        accept="image/png,image/jpeg,image/jpg,image/gif,image/webp"
        style={{ display: 'none' }}
        onChange={handleChange}
      />
    </div>
  )
}

const MissingPlaceholder = ({ label }) => (
  <div className="contribute-upload-placeholder contribute-upload-placeholder--readonly" title={`${label} missing`}>
    <ImagePlaceholderIcon />
  </div>
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
  const [lightbox, setLightbox] = useState(null) // { url, alt }
  const { isAdmin } = useAuth()

  const openLightbox = useCallback((url, alt) => setLightbox({ url, alt }), [])
  const closeLightbox = useCallback(() => setLightbox(null), [])

  const loadGames = useCallback(async () => {
    try {
      setLoading(true)
      const response = await getContributeGames(systemId)
      const games = response.games || []
      setAllGames(games)
      if (games.length > 0) setSystemName(games[0].systemName || systemId)
    } catch (err) {
      console.error('Error loading contribute games:', err)
      setError('Failed to load games')
    } finally {
      setLoading(false)
    }
  }, [systemId])

  useEffect(() => { loadGames() }, [loadGames])

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

  const getGameUrl = (game) => {
    let gameId = game.id.replace(/^\.\//, '')
    if (gameId.startsWith(`${game.system}/`)) gameId = gameId.substring(game.system.length + 1)
    return `/game/${game.system}/${encodeURIComponent(gameId)}`
  }

  const mediaExists = (val) => val ? 1 : 0

  const filteredGames = allGames
    .filter(game => {
      if (selectedLetter) {
        const firstChar = (game.name || '').trim()[0] || ''
        if (selectedLetter === '#') { if (/[A-Za-z]/.test(firstChar)) return false }
        else { if (firstChar.toUpperCase() !== selectedLetter) return false }
      }
      if (nameFilter && !(game.name || '').toLowerCase().includes(nameFilter.toLowerCase())) return false
      return true
    })
    .sort((a, b) => {
      let cmp = 0
      if (sortColumn === 'name') cmp = (a.name || '').localeCompare(b.name || '')
      else if (sortColumn === 'publisher') cmp = (a.publisher || '').localeCompare(b.publisher || '')
      else if (sortColumn === 'releaseDate') cmp = (formatReleaseYear(a.releasedate) || '0').localeCompare(formatReleaseYear(b.releasedate) || '0')
      else if (['thumbnail', 'boxart', 'fanart', 'marquee', 'video'].includes(sortColumn))
        cmp = mediaExists(a[sortColumn]) - mediaExists(b[sortColumn])
      return sortDirection === 'desc' ? -cmp : cmp
    })

  const SortHeader = ({ column, label }) => (
    <th className="sortable" onClick={() => handleSort(column)} style={{ cursor: 'pointer' }}>
      {label} {sortColumn === column && (sortDirection === 'asc' ? '↑' : '↓')}
    </th>
  )

  // Renders a media cell: existing image (clickable for lightbox) or placeholder/upload
  const MediaThumbCell = ({ path, label, uploadProps }) => {
    if (path) {
      return (
        <td className="contribute-media-cell">
          <img
            src={getMediaUrl(path)}
            alt={label}
            className="contribute-media-thumb contribute-media-clickable"
            loading="lazy"
            onClick={() => openLightbox(getMediaUrl(path), label)}
          />
        </td>
      )
    }
    if (uploadProps) {
      return (
        <td className="contribute-media-cell contribute-media-missing">
          <UploadPlaceholder {...uploadProps} onUploadSuccess={loadGames} />
        </td>
      )
    }
    return (
      <td className="contribute-media-cell contribute-media-missing">
        <MissingPlaceholder label={label} />
      </td>
    )
  }

  if (loading && allGames.length === 0) return <div className="loading">Loading games...</div>
  if (error && allGames.length === 0) return <div className="error">{error}</div>

  return (
    <div className="system-games">
      {lightbox && <Lightbox url={lightbox.url} alt={lightbox.alt} onClose={closeLightbox} />}

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
          <button className={`letter-filter-btn ${selectedLetter === null ? 'active' : ''}`} onClick={() => setSelectedLetter(null)}>All</button>
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
                <SortHeader column="name" label="Game Name" />
                <SortHeader column="publisher" label="Publisher" />
                <SortHeader column="releaseDate" label="Year" />
                <SortHeader column="thumbnail" label="Thumbnail" />
                <SortHeader column="boxart" label="Boxart" />
                <SortHeader column="fanart" label="Fanart" />
                <SortHeader column="marquee" label="Marquee" />
                <SortHeader column="video" label="Video" />
              </tr>
            </thead>
            <tbody>
              {filteredGames.map((game) => {
                const gameUrl = getGameUrl(game)
                return (
                  <tr key={game.id} className="game-table-row">
                    <td className="game-name-cell">
                      <Link to={gameUrl} state={{ catalogType: 'wip' }} className="game-name">
                        {game.name}
                      </Link>
                    </td>
                    <td className="game-publisher-cell">{game.publisher || '-'}</td>
                    <td className="game-releaseyear-cell">{formatReleaseYear(game.releasedate) || '-'}</td>

                    <MediaThumbCell path={game.thumbnail} label="Thumbnail" />
                    <MediaThumbCell path={game.boxart} label="Boxart" />

                    <MediaThumbCell
                      path={game.fanart}
                      label="Fanart"
                      uploadProps={isAdmin ? { system: game.system, gameId: game.id, mediaType: 'fanart', label: 'Fanart' } : null}
                    />
                    <MediaThumbCell
                      path={game.marquee}
                      label="Marquee"
                      uploadProps={isAdmin ? { system: game.system, gameId: game.id, mediaType: 'marquee', label: 'Marquee' } : null}
                    />

                    <td className="contribute-media-cell">
                      {game.video
                        ? <span className="contribute-video-icon" title="Video available"><VideoIcon /></span>
                        : <MissingPlaceholder label="Video" />
                      }
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
