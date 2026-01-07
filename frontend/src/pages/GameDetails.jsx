import React, { useState, useEffect } from 'react'
import { useParams, useNavigate, Link } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { getMediaUrl } from '../utils/constants'
import MediaUpload from '../components/Media/MediaUpload'
import TokenSelectorDropdown from '../components/TokenSelector/TokenSelectorDropdown'
import { useDownloadWithToken } from '../hooks/useDownloadWithToken'
import client from '../api/client'
import './GameDetails.css'

const GameDetails = () => {
  const { system, gameId } = useParams()
  const navigate = useNavigate()
  const { isAdmin, isDownload, isFastDownload } = useAuth()
  const [game, setGame] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [selectedMedia, setSelectedMedia] = useState(null)
  const { addToQueue, handleTokenSelected, cancelTokenSelection, showTokenSelector } = useDownloadWithToken()

  useEffect(() => {
    loadGameDetails()
  }, [system, gameId])

  const loadGameDetails = async () => {
    try {
      setLoading(true)
      setError(null)
      // gameId is already URL encoded from the route parameter
      // The backend expects: system/game_path
      const response = await client.get(`/api/catalog/game/${system}/${encodeURIComponent(gameId)}`)
      setGame(response.data)
      
      // Set initial selected media (prefer boxart, then thumbnail, then image)
      if (response.data.boxart) {
        setSelectedMedia({ type: 'boxart', url: getMediaUrl(response.data.boxart) })
      } else if (response.data.thumbnail) {
        setSelectedMedia({ type: 'thumbnail', url: getMediaUrl(response.data.thumbnail) })
      } else if (response.data.image) {
        setSelectedMedia({ type: 'image', url: getMediaUrl(response.data.image) })
      }
    } catch (err) {
      console.error('Error loading game details:', err)
      setError('Failed to load game details')
    } finally {
      setLoading(false)
    }
  }

  const handleDownload = async () => {
    try {
      const result = await addToQueue(game.id)
      if (result && result.success) {
        alert('Game added to download queue!')
      }
      // If requiresSelection is true, TokenSelector will be shown automatically (no error thrown)
    } catch (error) {
      console.error('Error adding to download queue:', error)
      // Only show alert if it's not a token selection requirement (that's handled by the hook)
      const requiresSelection = error.response?.headers?.['x-requires-token-selection'] === 'true' ||
                                error.response?.headers?.['X-Requires-Token-Selection'] === 'true'
      if (!requiresSelection) {
        const errorMsg = error.response?.data?.detail || 'Failed to add game to download queue. Please try again.'
        alert(errorMsg)
      }
    }
  }

  const formatReleaseDate = (dateStr) => {
    if (!dateStr) return ''
    // Format: YYYYMMDDTHHMMSS -> YYYY-MM-DD
    if (dateStr.length >= 8) {
      const year = dateStr.substring(0, 4)
      const month = dateStr.substring(4, 6)
      const day = dateStr.substring(6, 8)
      return `${year}-${month}-${day}`
    }
    return dateStr
  }

  const getMediaItems = () => {
    if (!game) return []
    
    // Fields to exclude from display
    const excludedFields = ['mix', 'wheel', 'screenshot', 'video']
    
    const mediaTypes = [
      { key: 'boxart', label: 'Box Art' },
      { key: 'boxback', label: 'Box Back' },
      { key: 'thumbnail', label: 'Thumbnail' },
      { key: 'marquee', label: 'Marquee' },
      { key: 'fanart', label: 'Fan Art' },
      { key: 'cartridge', label: 'Cartridge' },
      { key: 'titleshot', label: 'Title Shot' },
      { key: 'image', label: 'Screenshot' },
      { key: 'extra1', label: 'Extra 1' },
      { key: 'spine', label: 'Spine' },
      // Excluded: screenshot, wheel, mix, video
    ]
    
    // Filter out excluded fields
    return mediaTypes
      .filter(type => !excludedFields.includes(type.key))
      .map(type => ({
        type: type.key,
        label: type.label,
        hasMedia: !!game[type.key],
        url: game[type.key] ? getMediaUrl(game[type.key]) : null
      }))
  }

  const handleUploadSuccess = () => {
    // Optionally reload game details or show a message
    // For now, just show success in the upload component
  }

  if (loading) {
    return <div className="game-details-loading">Loading game details...</div>
  }

  if (error || !game) {
    return (
      <div className="game-details-error">
        <p>{error || 'Game not found'}</p>
        <Link to="/systems">Back to Systems</Link>
      </div>
    )
  }

  const mediaItems = getMediaItems()

  return (
    <div className="game-details">
      <div className="game-details-header">
        <button className="back-btn" onClick={() => navigate(-1)}>
          ← Back
        </button>
        <Link to={`/system/${game.system}`} className="back-to-system">
          Back to {game.systemName}
        </Link>
      </div>

      <div className="game-details-content">
        <div className="game-details-main">
          <div className="game-details-media">
            {selectedMedia ? (
              <div className="main-media">
                <img 
                  src={selectedMedia.url} 
                  alt={game.name}
                  className="main-media-image"
                />
              </div>
            ) : (
              <div className="main-media no-image">
                <span>No image available</span>
              </div>
            )}

            {mediaItems.length > 0 && (
              <div className="media-thumbnails">
                {mediaItems.map((media) => {
                  // Only fanart and marquee can be uploaded (for admins)
                  const canUpload = isAdmin && (media.type === 'fanart' || media.type === 'marquee')
                  
                  if (media.hasMedia && !canUpload) {
                    // Regular media thumbnail (no upload)
                    return (
                      <div
                        key={media.type}
                        className={`media-thumbnail ${selectedMedia?.type === media.type ? 'active' : ''}`}
                        onClick={() => setSelectedMedia({ type: media.type, url: media.url })}
                      >
                        <img src={media.url} alt={media.label} />
                        <span className="media-label">{media.label}</span>
                      </div>
                    )
                  } else if (media.hasMedia && canUpload) {
                    // Media with upload option (fanart/marquee for admins)
                    return (
                      <div
                        key={media.type}
                        className={`media-thumbnail ${selectedMedia?.type === media.type ? 'active' : ''} with-upload`}
                      >
                        <div
                          className="media-thumbnail-image"
                          onClick={() => setSelectedMedia({ type: media.type, url: media.url })}
                        >
                          <img src={media.url} alt={media.label} />
                        </div>
                        <span className="media-label">{media.label}</span>
                        <MediaUpload
                          system={game.system}
                          gameId={game.id}
                          mediaType={media.type}
                          label={media.label}
                          onUploadSuccess={() => {
                            handleUploadSuccess()
                            loadGameDetails() // Reload to show new image
                          }}
                          compact={true}
                        />
                      </div>
                    )
                  } else if (canUpload) {
                    // No media, but can upload (fanart/marquee for admins)
                    return (
                      <MediaUpload
                        key={media.type}
                        system={game.system}
                        gameId={game.id}
                        mediaType={media.type}
                        label={media.label}
                        onUploadSuccess={() => {
                          handleUploadSuccess()
                          loadGameDetails() // Reload to show new image
                        }}
                      />
                    )
                  }
                  // For other media types without media, don't show anything
                  return null
                })}
              </div>
            )}
          </div>

          <div className="game-details-info">
            <h1 className="game-title">{game.name}</h1>
            
            {game.marquee && (
              <div className="game-marquee-logo">
                <img 
                  src={getMediaUrl(game.marquee)} 
                  alt={`${game.name} marquee`}
                  className="marquee-image"
                />
              </div>
            )}
            
            <div className="game-meta-grid">
              {game.developer && (
                <div className="meta-item">
                  <span className="meta-label">Developer:</span>
                  <span className="meta-value">{game.developer}</span>
                </div>
              )}
              {game.publisher && (
                <div className="meta-item">
                  <span className="meta-label">Publisher:</span>
                  <span className="meta-value">{game.publisher}</span>
                </div>
              )}
              {game.releaseDate && (
                <div className="meta-item">
                  <span className="meta-label">Release Date:</span>
                  <span className="meta-value">{formatReleaseDate(game.releaseDate)}</span>
                </div>
              )}
              {game.genre && (
                <div className="meta-item">
                  <span className="meta-label">Genre:</span>
                  <span className="meta-value">{game.genre}</span>
                </div>
              )}
              {game.players && (
                <div className="meta-item">
                  <span className="meta-label">Players:</span>
                  <span className="meta-value">{game.players}</span>
                </div>
              )}
              {game.rating && (
                <div className="meta-item">
                  <span className="meta-label">Rating:</span>
                  <span className="meta-value">{parseFloat(game.rating) * 5} / 5</span>
                </div>
              )}
              {game.region && (
                <div className="meta-item">
                  <span className="meta-label">Region:</span>
                  <span className="meta-value">{game.region.toUpperCase()}</span>
                </div>
              )}
              {game.lang && (
                <div className="meta-item">
                  <span className="meta-label">Language:</span>
                  <span className="meta-value">{game.lang}</span>
                </div>
              )}
            </div>

            {game.description && (
              <div className="game-description">
                <h2>Description</h2>
                <p>{game.description}</p>
              </div>
            )}

            {(isDownload || isFastDownload) && game?.download_enabled !== false && (
              <div className="game-actions">
                <button className="download-btn" onClick={handleDownload}>
                  Add to Download Queue
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
      <TokenSelectorDropdown
        isOpen={showTokenSelector}
        onClose={cancelTokenSelection}
        onSelect={handleTokenSelected}
        gameId={game?.id}
      />
    </div>
  )
}

export default GameDetails

