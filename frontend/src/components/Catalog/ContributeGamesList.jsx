import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'
import { useCatalog } from '../../context/CatalogContext'
import { getMediaUrl } from '../../utils/constants'
import { getContributeGames } from '../../api/catalog'
import client from '../../api/client'
import './SystemGames.css'
import './ContributeGamesList.css'

// ── Pure helpers (module scope — stable references) ──────────────────────────

const getRomFilename = (gameId) => {
  const clean = gameId.replace(/^\.\//, '')
  const basename = clean.split('/').pop()
  return basename.replace(/\.[^.]+$/, '')
}

const formatReleaseYear = (dateString) => {
  if (!dateString) return null
  const str = String(dateString)
  if (/^\d{8}/.test(str)) return str.substring(0, 4)
  const match = str.match(/^(\d{4})/)
  return match ? match[1] : null
}

const getGameUrl = (game) => {
  let gameId = game.id.replace(/^\.\//, '')
  if (gameId.startsWith(`${game.system}/`)) gameId = gameId.substring(game.system.length + 1)
  return `/game/${game.system}/${encodeURIComponent(gameId)}`
}

// ── Icons ─────────────────────────────────────────────────────────────────────

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

const VideoUploadIcon = () => (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
    <rect x="2" y="5" width="15" height="14" rx="2" stroke="currentColor" strokeWidth="1.5" fill="none" />
    <path d="M17 9l5-3v12l-5-3V9z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" fill="none" />
    <path d="M7 15v-5M4.5 12.5l2.5-2.5 2.5 2.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)

// ── Sub-components (module scope — stable references) ─────────────────────────

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

const MEDIA_TYPE_CONFIG = {
  marquee: { accept: 'image/png', types: ['image/png'], maxSize: 10 * 1024 * 1024, hint: 'PNG only' },
  fanart:  { accept: 'image/jpeg,image/jpg', types: ['image/jpeg', 'image/jpg'], maxSize: 10 * 1024 * 1024, hint: 'JPG only' },
  video:   { accept: 'video/mp4', types: ['video/mp4'], maxSize: 200 * 1024 * 1024, hint: 'MP4 only' },
}
const DEFAULT_IMAGE_CONFIG = { accept: 'image/png,image/jpeg,image/jpg,image/gif,image/webp', types: ['image/png', 'image/jpeg', 'image/jpg', 'image/gif', 'image/webp'], maxSize: 10 * 1024 * 1024, hint: 'Invalid type' }

const UploadPlaceholder = ({ system, gameId, mediaType, label, onUploadSuccess, isVideo }) => {
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState(null)
  const [success, setSuccess] = useState(false)
  const fileInputRef = useRef(null)
  const config = MEDIA_TYPE_CONFIG[mediaType] ?? DEFAULT_IMAGE_CONFIG

  const uploadFile = async (file) => {
    if (!config.types.includes(file.type)) { setError(config.hint); return }
    if (file.size > config.maxSize) { setError('Too large'); return }
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
      if (response.data.success) {
        setSuccess(true)
        const ext = file.name.split('.').pop().toLowerCase()
        const romFilename = getRomFilename(gameId)
        const previewUrl = `/api/media/my-pending-preview/${system}/${mediaType}/${romFilename}.${ext}`
        onUploadSuccess?.({ romFilename, mediaType, previewUrl })
      }
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
        <>{isVideo ? <VideoUploadIcon /> : <><ImagePlaceholderIcon /><UploadArrowIcon /></>}</>
      )}
      {error && <span className="placeholder-error">{error}</span>}
      <input
        ref={fileInputRef}
        type="file"
        accept={config.accept}
        style={{ display: 'none' }}
        onChange={handleChange}
      />
    </div>
  )
}

const MissingPlaceholder = ({ label, isVideo }) => (
  <div className="contribute-upload-placeholder contribute-upload-placeholder--readonly" title={`${label} missing`}>
    {isVideo ? <VideoUploadIcon /> : <ImagePlaceholderIcon />}
  </div>
)

const MediaThumbCell = ({ path, label, uploadProps, onLightboxOpen, pendingUrl }) => {
  if (path) {
    return (
      <td className="contribute-media-cell">
        <img
          src={getMediaUrl(path, 'wip')}
          alt={label}
          className="contribute-media-thumb contribute-media-clickable"
          loading="lazy"
          onClick={() => onLightboxOpen(getMediaUrl(path, 'wip'), label)}
        />
      </td>
    )
  }
  if (pendingUrl) {
    return (
      <td className="contribute-media-cell">
        <div className="contribute-pending-wrap">
          <img
            src={pendingUrl}
            alt={label}
            className="contribute-media-thumb contribute-media-clickable"
            loading="lazy"
            onClick={() => onLightboxOpen(pendingUrl, label)}
          />
          <span className="contribute-pending-badge" title="Pending validation">⏳</span>
        </div>
      </td>
    )
  }
  if (uploadProps) {
    return (
      <td className="contribute-media-cell contribute-media-missing">
        <UploadPlaceholder {...uploadProps} />
      </td>
    )
  }
  return (
    <td className="contribute-media-cell contribute-media-missing">
      <MissingPlaceholder label={label} />
    </td>
  )
}

// ── Memoized table — skipped entirely when only lightbox state changes ─────────

const ContributeGamesTable = React.memo(({
  filteredGames, sortColumn, sortDirection, onSort, canUpload, onLightboxOpen, onUploadSuccess, pendingMedia,
}) => {
  const SortHeader = ({ column, label }) => (
    <th className="sortable" onClick={() => onSort(column)} style={{ cursor: 'pointer' }}>
      {label} {sortColumn === column && (sortDirection === 'asc' ? '↑' : '↓')}
    </th>
  )

  return (
    <div className="games-table-container">
      <table className="games-table contribute-games-table">
        <thead>
          <tr>
            <SortHeader column="name" label="Game Name" />
            <SortHeader column="publisher" label="Publisher" />
            <SortHeader column="releaseDate" label="Year" />
            <SortHeader column="image" label="Image" />
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
            const romFilename = getRomFilename(game.id)
            const gamePending = pendingMedia[romFilename] || {}
            return (
              <tr key={game.id} className="game-table-row">
                <td className="game-name-cell">
                  <Link to={gameUrl} state={{ catalogType: 'wip' }} className="game-name">
                    {game.name}
                  </Link>
                </td>
                <td className="game-publisher-cell">{game.publisher || '-'}</td>
                <td className="game-releaseyear-cell">{formatReleaseYear(game.releasedate) || '-'}</td>

                <MediaThumbCell path={game.image} label="Image" onLightboxOpen={onLightboxOpen} />
                <MediaThumbCell path={game.thumbnail} label="Thumbnail" onLightboxOpen={onLightboxOpen} />
                <MediaThumbCell path={game.boxart} label="Boxart" onLightboxOpen={onLightboxOpen} />
                <MediaThumbCell
                  path={game.fanart}
                  label="Fanart"
                  onLightboxOpen={onLightboxOpen}
                  pendingUrl={gamePending.fanart}
                  uploadProps={canUpload && !gamePending.fanart ? { system: game.system, gameId: game.id, mediaType: 'fanart', label: 'Fanart', onUploadSuccess } : null}
                />
                <MediaThumbCell
                  path={game.marquee}
                  label="Marquee"
                  onLightboxOpen={onLightboxOpen}
                  pendingUrl={gamePending.marquee}
                  uploadProps={canUpload && !gamePending.marquee ? { system: game.system, gameId: game.id, mediaType: 'marquee', label: 'Marquee', onUploadSuccess } : null}
                />
                <td className="contribute-media-cell">
                  {game.video
                    ? <span className="contribute-video-icon" title="Video available"><VideoIcon /></span>
                    : gamePending.video
                      ? (
                        <div className="contribute-pending-wrap contribute-video-pending" title="Video pending validation">
                          <VideoIcon />
                          <span className="contribute-pending-badge">⏳</span>
                        </div>
                      )
                      : canUpload
                        ? <UploadPlaceholder system={game.system} gameId={game.id} mediaType="video" label="Video" onUploadSuccess={onUploadSuccess} isVideo />
                        : <MissingPlaceholder label="Video" isVideo />
                  }
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
})

// ── Main component ────────────────────────────────────────────────────────────

const ContributeGamesList = ({ systemId }) => {
  const [allGames, setAllGames] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [systemName, setSystemName] = useState('')
  const [selectedLetter, setSelectedLetter] = useState(null)
  const [nameFilter, setNameFilter] = useState('')
  const [sortColumn, setSortColumn] = useState('name')
  const [sortDirection, setSortDirection] = useState('asc')
  const [lightbox, setLightbox] = useState(null)
  const [pendingMedia, setPendingMedia] = useState({})
  const { isAdmin } = useAuth()
  const { canContribute } = useCatalog()
  const canUpload = isAdmin || canContribute

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

  const loadPendingMedia = useCallback(async () => {
    try {
      const response = await client.get('/api/media/my-pending', { params: { system: systemId } })
      const pending = response.data.pending_media || []
      const map = {}
      for (const item of pending) {
        const romName = item.filename.replace(/\.[^.]+$/, '')
        if (!map[romName]) map[romName] = {}
        map[romName][item.fieldname] = `/api/media/my-pending-preview/${item.system}/${item.fieldname}/${item.filename}`
      }
      setPendingMedia(map)
    } catch {
      // non-critical — contributors without pending files will get 200 with empty list,
      // non-contributors will get 403 which we silently ignore
    }
  }, [systemId])

  const handleUploadSuccess = useCallback(({ romFilename, mediaType, previewUrl }) => {
    setPendingMedia(prev => ({
      ...prev,
      [romFilename]: { ...(prev[romFilename] || {}), [mediaType]: previewUrl },
    }))
  }, [])

  useEffect(() => { loadGames() }, [loadGames])
  useEffect(() => { loadPendingMedia() }, [loadPendingMedia])

  const handleSort = useCallback((column) => {
    setSortColumn(prev => {
      if (prev === column) {
        setSortDirection(dir => dir === 'asc' ? 'desc' : 'asc')
        return column
      }
      setSortDirection('asc')
      return column
    })
  }, [])

  const letters = useMemo(
    () => ['#', ...Array.from({ length: 26 }, (_, i) => String.fromCharCode(65 + i))],
    []
  )

  // lightbox is intentionally NOT in deps — changing it must not recompute the list
  const filteredGames = useMemo(() => {
    const mediaFields = ['image', 'thumbnail', 'boxart', 'fanart', 'marquee', 'video']
    return allGames
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
        else if (mediaFields.includes(sortColumn)) cmp = (a[sortColumn] ? 1 : 0) - (b[sortColumn] ? 1 : 0)
        return sortDirection === 'desc' ? -cmp : cmp
      })
  }, [allGames, selectedLetter, nameFilter, sortColumn, sortDirection])

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
        <ContributeGamesTable
          filteredGames={filteredGames}
          sortColumn={sortColumn}
          sortDirection={sortDirection}
          onSort={handleSort}
          canUpload={canUpload}
          onLightboxOpen={openLightbox}
          onUploadSuccess={handleUploadSuccess}
          pendingMedia={pendingMedia}
        />
      )}
    </div>
  )
}

export default ContributeGamesList
