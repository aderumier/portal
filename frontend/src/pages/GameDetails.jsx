import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import { useParams, useNavigate, useLocation, Link } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { useCatalog } from '../context/CatalogContext'
import { getMediaUrl } from '../utils/constants'
import TokenSelectorDropdown from '../components/TokenSelector/TokenSelectorDropdown'
import WarningModal from '../components/WarningModal/WarningModal'
import BugReportModal from '../components/BugReport/BugReportModal'
import { useDownloadWithToken } from '../hooks/useDownloadWithToken'
import { getGameDetails } from '../api/catalog'
import './GameDetails.css'

const GameDetails = () => {
  const { system, gameId } = useParams()
  const navigate = useNavigate()
  const location = useLocation()
  const { isDownload, isFastDownload, isAuthenticated } = useAuth()
  const { catalogType } = useCatalog()
  const [game, setGame] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [selectedMedia, setSelectedMedia] = useState(null)
  const [showBugReportModal, setShowBugReportModal] = useState(false)
  const { addToQueue, handleTokenSelected, cancelTokenSelection, showTokenSelector, showOldClientWarning, setShowOldClientWarning } = useDownloadWithToken()

  // Prev/next navigation from system game list
  const fromSystemGames = location.state?.fromSystemGames
  const navSystemId = location.state?.systemId
  const preferredMediaType = location.state?.preferredMediaType
  const [gameNavList, setGameNavList] = useState([])

  useEffect(() => {
    if (fromSystemGames && navSystemId) {
      const stored = sessionStorage.getItem(`gameNavList_${navSystemId}`)
      if (stored) {
        try { setGameNavList(JSON.parse(stored)) } catch (e) { /* ignore */ }
      }
    }
  }, [fromSystemGames, navSystemId])

  const currentNavIndex = useMemo(() => {
    if (!gameNavList.length) return -1
    return gameNavList.findIndex(id => {
      let normalized = id.replace(/^\.\//, '')
      if (normalized.startsWith(`${system}/`)) normalized = normalized.substring(system.length + 1)
      return normalized === gameId
    })
  }, [gameNavList, gameId, system])

  const prevNavId = currentNavIndex > 0 ? gameNavList[currentNavIndex - 1] : null
  const nextNavId = currentNavIndex >= 0 && currentNavIndex < gameNavList.length - 1 ? gameNavList[currentNavIndex + 1] : null

  const navigateToNavGame = useCallback((id) => {
    let gId = id.replace(/^\.\//, '')
    if (gId.startsWith(`${system}/`)) gId = gId.substring(system.length + 1)
    navigate(`/game/${system}/${encodeURIComponent(gId)}`, {
      state: { fromSystemGames: true, systemId: navSystemId, preferredMediaType: selectedMedia?.type }
    })
  }, [navigate, system, navSystemId, selectedMedia])

  useEffect(() => {
    if (!fromSystemGames) return
    const handleKeyDown = (e) => {
      if (e.key === 'ArrowLeft' && prevNavId) navigateToNavGame(prevNavId)
      else if (e.key === 'ArrowRight' && nextNavId) navigateToNavGame(nextNavId)
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [fromSystemGames, prevNavId, nextNavId, navigateToNavGame])

  const isLoadingRef = useRef(false)
  const lastLoadKeyRef = useRef(null)
  const hasLoadedRef = useRef(false)

  const loadGameDetails = useCallback(async () => {
    const currentLoadKey = `${system}-${gameId}-${catalogType}`

    // Prevent duplicate calls: if we're already loading or have loaded the same game, skip
    if (lastLoadKeyRef.current === currentLoadKey) {
      if (isLoadingRef.current || hasLoadedRef.current) {
        return
      }
    }

    // Mark as loading immediately to prevent concurrent calls
    isLoadingRef.current = true
    lastLoadKeyRef.current = currentLoadKey
    hasLoadedRef.current = false

    try {
      setLoading(true)
      setError(null)
      // gameId is already URL encoded from the route parameter
      // The backend expects: system/game_path
      const gameData = await getGameDetails(system, gameId, catalogType)
      setGame(gameData)
      hasLoadedRef.current = true

      // Set initial selected media: use preferred type from nav if available, else boxart → thumbnail → image
      if (preferredMediaType && gameData[preferredMediaType]) {
        setSelectedMedia({ type: preferredMediaType, url: getMediaUrl(gameData[preferredMediaType]) })
      } else if (gameData.boxart) {
        setSelectedMedia({ type: 'boxart', url: getMediaUrl(gameData.boxart) })
      } else if (gameData.thumbnail) {
        setSelectedMedia({ type: 'thumbnail', url: getMediaUrl(gameData.thumbnail) })
      } else if (gameData.image) {
        setSelectedMedia({ type: 'image', url: getMediaUrl(gameData.image) })
      }
    } catch (err) {
      console.error('Error loading game details:', err)
      setError('Failed to load game details')
      // Reset refs on error so retry can work
      if (lastLoadKeyRef.current === currentLoadKey) {
        lastLoadKeyRef.current = null
        hasLoadedRef.current = false
      }
    } finally {
      setLoading(false)
      isLoadingRef.current = false
    }
  }, [system, gameId, catalogType, preferredMediaType])

  useEffect(() => {
    // Reset state when dependencies change to a different game
    const currentLoadKey = `${system}-${gameId}`
    if (lastLoadKeyRef.current !== currentLoadKey) {
      isLoadingRef.current = false
      hasLoadedRef.current = false
      lastLoadKeyRef.current = null
    }
    loadGameDetails()
  }, [system, gameId, loadGameDetails])

  const handleDownload = async () => {
    try {
      const result = await addToQueue(game.id, game.system)
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

  if (loading) {
    return <div className="game-details-loading">Loading game details...</div>
  }

  if (error || !game) {
    return (
      <div className="game-details-error">
        <p>{error || 'Game not found'}</p>
        <Link to="/releases">Back to Systems</Link>
      </div>
    )
  }

  const mediaItems = getMediaItems()

  return (
    <div className="game-details">
      {prevNavId && (
        <button className="game-nav-btn game-nav-prev" onClick={() => navigateToNavGame(prevNavId)} title="Previous game (←)">
          ‹
        </button>
      )}
      {nextNavId && (
        <button className="game-nav-btn game-nav-next" onClick={() => navigateToNavGame(nextNavId)} title="Next game (→)">
          ›
        </button>
      )}
      <div className="game-details-header">
        <button className="back-btn" onClick={() => navigate(-1)}>
          ← Back
        </button>
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
                  if (!media.hasMedia) return null
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
                })}
              </div>
            )}
          </div>

          <div className="game-details-info">
            <h1 className="game-title">{game.name}</h1>
            {isAuthenticated && (
              <button
                className="bug-report-button"
                onClick={() => setShowBugReportModal(true)}
                title="Report a bug"
              >
                🐛 Report Bug
              </button>
            )}

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

            {game.desc && (
              <div className="game-description">
                <h2>Description</h2>
                <p>{game.desc}</p>
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
      <WarningModal
        isOpen={showOldClientWarning}
        onClose={() => setShowOldClientWarning(false)}
        title="Update Required"
        message="Your client version is too old. Please update your client to download games."
      />
      <BugReportModal
        isOpen={showBugReportModal}
        onClose={() => setShowBugReportModal(false)}
        gameInfo={{
          rompath: game?.id || gameId,
          system: game?.system || system,
          catalog: catalogType
        }}
      />
    </div>
  )
}

export default GameDetails

