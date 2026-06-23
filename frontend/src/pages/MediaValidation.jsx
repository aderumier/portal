import React, { useState, useEffect, useCallback } from 'react'
import { useAuth } from '../context/AuthContext'
import { API_URL, getMediaUrl } from '../utils/constants'
import client from '../api/client'
import { getGameDetails } from '../api/catalog'
import ImageCropper from '../components/ImageCropper/ImageCropper'
import './MediaValidation.css'

const Lightbox = ({ url, media, startCropping = false, canCrop = false, onCropSave, onClose }) => {
  const [activeTab, setActiveTab] = useState('uploaded')
  const [game, setGame] = useState(null)
  const [gameLoading, setGameLoading] = useState(false)
  const [cropping, setCropping] = useState(startCropping)

  const alt = media?.filename
  const system = media?.system
  const gameId = media?.game_id

  useEffect(() => {
    const handleKey = (e) => { if (e.key === 'Escape') cropping ? setCropping(false) : onClose() }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [onClose, cropping])

  // Fetch game details to populate the Box Art / Screenshot tabs
  useEffect(() => {
    if (!gameId) return
    setGameLoading(true)
    getGameDetails(system, gameId, 'wip')
      .then(data => { setGame(data); setGameLoading(false) })
      .catch(() => { setGameLoading(false) })
  }, [system, gameId])

  const boxartUrl = game ? getMediaUrl(game.boxart) : null
  const screenshotUrl = game ? getMediaUrl(game.image) : null

  const tabs = [
    { key: 'uploaded', label: 'Uploaded', src: url },
    { key: 'boxart', label: 'Box Art', src: boxartUrl },
    { key: 'screenshot', label: 'Screenshot', src: screenshotUrl },
  ]

  const activeSrc = tabs.find(t => t.key === activeTab)?.src
  const cropActive = cropping && activeTab === 'uploaded'

  const selectTab = (key) => { setCropping(false); setActiveTab(key) }

  return (
    <div className="mv-lightbox-overlay" onClick={() => (cropping ? setCropping(false) : onClose())}>
      <div className="mv-lightbox-content" onClick={(e) => e.stopPropagation()}>
        <div className="mv-lightbox-tabs">
          {tabs.map(tab => (
            <button
              key={tab.key}
              className={`mv-lightbox-tab${activeTab === tab.key ? ' active' : ''}`}
              onClick={() => selectTab(tab.key)}
            >
              {tab.label}
            </button>
          ))}
          {canCrop && activeTab === 'uploaded' && !cropActive && (
            <button className="mv-lightbox-tab mv-lightbox-crop-toggle" onClick={() => setCropping(true)}>
              ✂ Crop
            </button>
          )}
        </div>
        <div className="mv-lightbox-stage">
          {cropActive ? (
            <ImageCropper
              imageUrl={url}
              filename={media.filename}
              onApply={async (blob) => { await onCropSave(blob); setCropping(false) }}
              onCancel={() => setCropping(false)}
            />
          ) : activeSrc ? (
            <img src={activeSrc} alt={alt} className="mv-lightbox-image" />
          ) : (
            <div className="mv-lightbox-empty">
              {gameLoading ? 'Loading…' : `No ${tabs.find(t => t.key === activeTab)?.label.toLowerCase()} available`}
            </div>
          )}
        </div>
      </div>
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

const VIDEO_EXTENSIONS = new Set(['.mp4', '.webm', '.ogg', '.mov', '.avi', '.mkv'])

const isVideoFile = (filename) => {
  const ext = filename.slice(filename.lastIndexOf('.')).toLowerCase()
  return VIDEO_EXTENSIONS.has(ext)
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
  const [validatingKey, setValidatingKey] = useState(null)
  const [cropVersions, setCropVersions] = useState({})

  const openLightbox = useCallback((media, cropping = false) => setLightbox({ media, cropping }), [])
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

  const validateOne = async (system, fieldname, filename, userId) => {
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
  }

  const handleValidate = async (system, fieldname, filename, userId) => {
    try {
      await validateOne(system, fieldname, filename, userId)
      setPendingMedia(prev => prev.filter(m => !(
        m.system === system &&
        m.fieldname === fieldname &&
        m.filename === filename &&
        (userId ? m.user_id === userId : true)
      )))
    } catch (err) {
      console.error('Error validating media:', err)
      alert(err.response?.data?.detail || 'Failed to validate media')
    }
  }

  const handleValidateAll = async (groupKey, mediaList) => {
    if (mediaList.length === 0) return
    const { system, fieldname } = mediaList[0]
    if (!confirm(`Validate all ${mediaList.length} ${system} / ${fieldname} file${mediaList.length !== 1 ? 's' : ''}?`)) {
      return
    }

    setValidatingKey(groupKey)
    try {
      const items = mediaList.map(media => ({
        system: media.system,
        fieldname: media.fieldname,
        filename: media.filename,
        user_id: media.user_id || null,
      }))
      const response = await client.post('/api/media/validate-batch', { items })
      const failed = response.data?.failed || []
      const failedNames = new Set(failed.map(f => f.filename))
      // Remove the successfully validated items from this group, keep failures
      setPendingMedia(prev => prev.filter(m => !(
        m.system === system &&
        m.fieldname === fieldname &&
        !failedNames.has(m.filename)
      )))
      if (failed.length > 0) {
        alert(`Failed to validate ${failed.length} file(s):\n${failed.map(f => f.filename).join('\n')}`)
      }
    } catch (err) {
      console.error('Error validating media:', err)
      alert(err.response?.data?.detail || 'Failed to validate media')
    } finally {
      setValidatingKey(null)
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

      setPendingMedia(prev => prev.filter(m => !(
        m.system === system &&
        m.fieldname === fieldname &&
        m.filename === filename &&
        (userId ? m.user_id === userId : true)
      )))
    } catch (err) {
      console.error('Error deleting media:', err)
      alert(err.response?.data?.detail || 'Failed to delete media')
    }
  }

  const handleCropApply = async (media, blob) => {
    const formData = new FormData()
    formData.append('system', media.system)
    formData.append('fieldname', media.fieldname)
    formData.append('filename', media.filename)
    if (media.user_id) {
      formData.append('user_id', media.user_id)
    }
    formData.append('file', blob, media.filename)
    try {
      await client.post('/api/media/pending/crop', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      const dimKey = `${media.user_id}/${media.system}/${media.fieldname}/${media.filename}`
      setCropVersions(prev => ({ ...prev, [dimKey]: Date.now() }))
      setDimensions(prev => { const next = { ...prev }; delete next[dimKey]; return next })
    } catch (err) {
      alert(err.response?.data?.detail || 'Failed to crop image')
      throw err
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
      {lightbox && (() => {
        const m = lightbox.media
        const dimKey = `${m.user_id}/${m.system}/${m.fieldname}/${m.filename}`
        const ver = cropVersions[dimKey]
        const url = `${API_URL}/api/media/pending-preview/${m.user_id || 'unknown'}/${m.system}/${m.fieldname}/${encodeURIComponent(m.filename)}${ver ? `?v=${ver}` : ''}`
        return (
          <Lightbox
            url={url}
            media={m}
            startCropping={lightbox.cropping}
            canCrop={!isVideoFile(m.filename)}
            onCropSave={(blob) => handleCropApply(m, blob)}
            onClose={closeLightbox}
          />
        )
      })()}
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
                <div className="media-group-header">
                  <h2 className="media-group-title">
                    {system} / {fieldname} ({mediaList.length} file{mediaList.length !== 1 ? 's' : ''})
                  </h2>
                  <button
                    className="validate-all-button"
                    onClick={() => handleValidateAll(key, mediaList)}
                    disabled={validatingKey === key}
                  >
                    {validatingKey === key ? 'Validating…' : 'Validate All'}
                  </button>
                </div>
                <div className="media-list">
                  {mediaList.map((media, index) => {
                    const dimKey = `${media.user_id}/${media.system}/${media.fieldname}/${media.filename}`
                    const cropVersion = cropVersions[dimKey]
                    const previewUrl = `${API_URL}/api/media/pending-preview/${media.user_id || 'unknown'}/${media.system}/${media.fieldname}/${encodeURIComponent(media.filename)}${cropVersion ? `?v=${cropVersion}` : ''}`
                    const dim = dimensions[dimKey]
                    return (
                      <div key={index} className="media-item">
                        <div className="media-item-preview">
                          {isVideoFile(media.filename) ? (
                            <video
                              src={previewUrl}
                              className="media-item-preview-video"
                              controls
                              preload="metadata"
                            />
                          ) : (
                            <>
                              <img
                                src={previewUrl}
                                alt={media.filename}
                                className="media-item-preview-img"
                                onClick={() => openLightbox(media)}
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
                            </>
                          )}
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
                          {!isVideoFile(media.filename) && (
                            <button
                              className="crop-button"
                              onClick={() => openLightbox(media, true)}
                            >
                              Crop
                            </button>
                          )}
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

