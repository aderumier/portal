import React, { useState, useEffect, useCallback } from 'react'
import { useAuth } from '../context/AuthContext'
import { API_URL, getMediaUrl } from '../utils/constants'
import client from '../api/client'
import { getGameDetails } from '../api/catalog'
import './MediaValidation.css'

const Lightbox = ({ url, alt, onClose }) => {
  useEffect(() => {
    const handleKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [onClose])

  return (
    <div className="mv-lightbox-overlay" onClick={onClose}>
      <img
        src={url}
        alt={alt}
        className="mv-lightbox-image"
        onClick={(e) => e.stopPropagation()}
      />
      <button className="mv-lightbox-close" onClick={onClose}>✕</button>
    </div>
  )
}

const GameInfoModal = ({ system, gameId, gameName, onClose }) => {
  const [game, setGame] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    const handleKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [onClose])

  useEffect(() => {
    if (!gameId) { setLoading(false); return }
    setLoading(true)
    getGameDetails(system, gameId, 'wip')
      .then(data => { setGame(data); setLoading(false) })
      .catch(() => { setError('Failed to load game details'); setLoading(false) })
  }, [system, gameId])

  // Same field list as GameDetails.jsx — image is screenshot, NOT boxart
  const IMAGE_FIELDS = [
    { key: 'boxart',    label: 'Box Art' },
    { key: 'boxback',   label: 'Box Back' },
    { key: 'fanart',    label: 'Fan Art' },
    { key: 'marquee',   label: 'Marquee' },
    { key: 'cartridge', label: 'Cartridge' },
    { key: 'titleshot', label: 'Title Shot' },
    { key: 'thumbnail', label: 'Thumbnail' },
    { key: 'image',     label: 'Screenshot' },
  ]

  const images = game
    ? IMAGE_FIELDS.map(f => ({ label: f.label, url: getMediaUrl(game[f.key]) })).filter(f => f.url)
    : []

  const formatYear = (d) => d ? String(d).substring(0, 4) : null

  return (
    <div className="mv-game-modal-overlay" onClick={onClose}>
      <div className="mv-game-modal" onClick={(e) => e.stopPropagation()}>
        <button className="mv-lightbox-close" onClick={onClose}>✕</button>

        {loading && <div className="mv-game-modal-loading">Loading…</div>}
        {error && <div className="mv-game-modal-error">{error}</div>}
        {!loading && !error && game && (
          <>
            <h2 className="mv-game-modal-title">{game.name || gameName}</h2>
            <div className="mv-game-modal-meta">
              {game.developer && <span><strong>Developer:</strong> {game.developer}</span>}
              {game.publisher && <span><strong>Publisher:</strong> {game.publisher}</span>}
              {game.genre && <span><strong>Genre:</strong> {game.genre}</span>}
              {formatYear(game.releasedate) && <span><strong>Year:</strong> {formatYear(game.releasedate)}</span>}
            </div>
            {game.desc && <p className="mv-game-modal-desc">{game.desc}</p>}
            {images.length > 0 && (
              <div className="mv-game-modal-images">
                {images.map(({ label, url }) => (
                  <div key={label} className="mv-game-modal-image-wrap">
                    <img src={url} alt={label} className="mv-game-modal-image" />
                    <span className="mv-game-modal-image-label">{label}</span>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
        {!loading && !error && !game && (
          <div className="mv-game-modal-error">Game not found in catalog.</div>
        )}
      </div>
    </div>
  )
}

const MediaValidation = () => {
  const { isAdmin } = useAuth()
  const [pendingMedia, setPendingMedia] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [filterSystem, setFilterSystem] = useState('')
  const [filterFieldname, setFilterFieldname] = useState('')
  const [lightbox, setLightbox] = useState(null)
  const [dimensions, setDimensions] = useState({})
  const [gameModal, setGameModal] = useState(null)

  const openLightbox = useCallback((url, alt) => setLightbox({ url, alt }), [])
  const closeLightbox = useCallback(() => setLightbox(null), [])
  const openGameModal = useCallback((system, gameId, gameName) => setGameModal({ system, gameId, gameName }), [])
  const closeGameModal = useCallback(() => setGameModal(null), [])

  const handleImageLoad = useCallback((key, e) => {
    const { naturalWidth, naturalHeight } = e.target
    if (naturalWidth && naturalHeight) {
      setDimensions(prev => ({ ...prev, [key]: { w: naturalWidth, h: naturalHeight } }))
    }
  }, [])

  useEffect(() => {
    if (isAdmin) {
      loadPendingMedia()
    }
  }, [isAdmin])

  const loadPendingMedia = async () => {
    try {
      setLoading(true)
      setError(null)
      const response = await client.get('/api/media/pending')
      setPendingMedia(response.data.pending_media || [])
    } catch (err) {
      console.error('Error loading pending media:', err)
      setError('Failed to load pending media')
    } finally {
      setLoading(false)
    }
  }

  const handleValidate = async (system, fieldname, filename, userId) => {
    if (!confirm(`Validate and move ${filename}?`)) {
      return
    }

    try {
      const formData = new FormData()
      formData.append('system', system)
      formData.append('fieldname', fieldname)
      formData.append('filename', filename)
      if (userId) {
        formData.append('user_id', userId)
      }

      await client.post('/api/media/validate', formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      })

      alert('Media validated and moved successfully!')
      loadPendingMedia()
    } catch (err) {
      console.error('Error validating media:', err)
      alert(err.response?.data?.detail || 'Failed to validate media')
    }
  }

  const handleDelete = async (system, fieldname, filename, userId) => {
    if (!confirm(`Delete ${filename}?`)) {
      return
    }

    try {
      const params = {
        system,
        fieldname,
        filename
      }
      if (userId) {
        params.user_id = userId
      }

      await client.delete('/api/media/pending', { params })

      alert('Pending media deleted successfully!')
      loadPendingMedia()
    } catch (err) {
      console.error('Error deleting media:', err)
      alert(err.response?.data?.detail || 'Failed to delete media')
    }
  }

  // Get unique systems and fieldnames for filters
  const systems = [...new Set(pendingMedia.map(m => m.system))].sort()
  const fieldnames = [...new Set(pendingMedia.map(m => m.fieldname))].sort()

  // Filter media
  const filteredMedia = pendingMedia.filter(media => {
    if (filterSystem && media.system !== filterSystem) return false
    if (filterFieldname && media.fieldname !== filterFieldname) return false
    return true
  })

  // Group by system and fieldname
  const groupedMedia = filteredMedia.reduce((acc, media) => {
    const key = `${media.system}/${media.fieldname}`
    if (!acc[key]) {
      acc[key] = []
    }
    acc[key].push(media)
    return acc
  }, {})

  if (!isAdmin) {
    return (
      <div className="media-validation-page">
        <div className="media-validation-error">
          <p>You must have Admin role to access media validation.</p>
        </div>
      </div>
    )
  }

  if (loading) {
    return (
      <div className="media-validation-page">
        <div className="media-validation-loading">Loading pending media...</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="media-validation-page">
        <div className="media-validation-error">{error}</div>
      </div>
    )
  }

  return (
    <div className="media-validation-page">
      {lightbox && <Lightbox url={lightbox.url} alt={lightbox.alt} onClose={closeLightbox} />}
      {gameModal && <GameInfoModal system={gameModal.system} gameId={gameModal.gameId} gameName={gameModal.gameName} onClose={closeGameModal} />}
      <h1>Media Validation</h1>
      <p className="media-validation-description">
        Review and validate user-uploaded media files. Validated files will be moved to the game media directories.
      </p>

      <div className="media-validation-filters">
        <div className="filter-group">
          <label>System:</label>
          <select
            value={filterSystem}
            onChange={(e) => setFilterSystem(e.target.value)}
          >
            <option value="">All Systems</option>
            {systems.map(system => (
              <option key={system} value={system}>{system}</option>
            ))}
          </select>
        </div>

        <div className="filter-group">
          <label>Media Type:</label>
          <select
            value={filterFieldname}
            onChange={(e) => setFilterFieldname(e.target.value)}
          >
            <option value="">All Types</option>
            {fieldnames.map(fieldname => (
              <option key={fieldname} value={fieldname}>{fieldname}</option>
            ))}
          </select>
        </div>

        <div className="filter-group">
          <button onClick={loadPendingMedia} className="refresh-button">
            Refresh
          </button>
        </div>
      </div>

      {Object.keys(groupedMedia).length === 0 ? (
        <div className="no-pending-media">
          <p>No pending media files found.</p>
        </div>
      ) : (
        <div className="media-validation-groups">
          {Object.entries(groupedMedia).map(([key, mediaList]) => {
            const [system, fieldname] = key.split('/')
            return (
              <div key={key} className="media-group">
                <h2 className="media-group-title">
                  {system} / {fieldname} ({mediaList.length} file{mediaList.length !== 1 ? 's' : ''})
                </h2>
                <div className="media-list">
                  {mediaList.map((media, index) => {
                    const previewUrl = `${API_URL}/api/media/pending-preview/${media.user_id || 'unknown'}/${media.system}/${media.fieldname}/${encodeURIComponent(media.filename)}`
                    const dimKey = `${media.user_id}/${media.system}/${media.fieldname}/${media.filename}`
                    const dim = dimensions[dimKey]
                    return (
                      <div key={index} className="media-item">
                        <div className="media-item-preview">
                          <img
                            src={previewUrl}
                            alt={media.filename}
                            className="media-item-preview-img"
                            onClick={() => openLightbox(previewUrl, media.filename)}
                            onLoad={(e) => handleImageLoad(dimKey, e)}
                            onError={(e) => {
                              e.target.style.display = 'none'
                              const placeholder = e.target.nextElementSibling
                              if (placeholder) placeholder.style.display = 'flex'
                            }}
                          />
                          <div className="media-item-placeholder" style={{ display: 'none' }}>
                            <i className="fas fa-image"></i>
                          </div>
                        </div>
                        <div className="media-item-info">
                          <div
                            className="media-item-gamename media-item-gamename--link"
                            onClick={() => openGameModal(media.system, media.game_id, media.game_name)}
                            title="View game info"
                          >{media.game_name || media.filename}</div>
                          <div className="media-item-filename">{media.filename}</div>
                          {dim && (
                            <div className="media-item-meta">{dim.w} × {dim.h} px</div>
                          )}
                          {media.username && (
                            <div className="media-item-meta">
                              Uploaded by: <strong>{media.username}</strong>
                            </div>
                          )}
                          <div className="media-item-meta">
                            Uploaded: {new Date(media.upload_date).toLocaleString()}
                          </div>
                          <div className="media-item-meta">
                            Size: {(media.size / 1024).toFixed(2)} KB
                          </div>
                        </div>
                        <div className="media-item-actions">
                          <button
                            className="validate-button"
                            onClick={() => handleValidate(media.system, media.fieldname, media.filename, media.user_id)}
                          >
                            Validate
                          </button>
                          <button
                            className="delete-button"
                            onClick={() => handleDelete(media.system, media.fieldname, media.filename, media.user_id)}
                          >
                            Delete
                          </button>
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

export default MediaValidation

