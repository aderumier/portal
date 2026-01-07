import React, { useState, useEffect, useRef, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import GameCard from './GameCard'
import TokenSelectorDropdown from '../TokenSelector/TokenSelectorDropdown'
import { useDownloadWithToken } from '../../hooks/useDownloadWithToken'
import { useAuth } from '../../context/AuthContext'
import { getMediaUrl } from '../../utils/constants'
import client from '../../api/client'
import './SystemGames.css'

const SystemGames = ({ systemId, systemName, searchQuery = '' }) => {
  const [games, setGames] = useState([])
  const [loading, setLoading] = useState(true)
  const [hasMore, setHasMore] = useState(true)
  const [page, setPage] = useState(1)
  const [error, setError] = useState(null)
  const [viewMode, setViewMode] = useState('grid') // 'grid' or 'table'
  const [selectedSubdirectory, setSelectedSubdirectory] = useState(null) // null = all, or specific subdirectory
  const observerRef = useRef(null)
  const loadingRef = useRef(null)
  const navigate = useNavigate()
  const { addToQueue, handleTokenSelected, cancelTokenSelection, showTokenSelector } = useDownloadWithToken()
  const { isDownload, isFastDownload } = useAuth()

  // Load view preference from localStorage
  useEffect(() => {
    const savedView = localStorage.getItem('systemGamesViewMode')
    if (savedView === 'table' || savedView === 'grid') {
      setViewMode(savedView)
    }
  }, [])

  // Save view preference to localStorage
  const handleViewChange = (mode) => {
    setViewMode(mode)
    localStorage.setItem('systemGamesViewMode', mode)
  }

  const loadGames = useCallback(async (pageNum, append = false) => {
    try {
      setLoading(true)
      setError(null)
      
      const params = {
        page: pageNum,
        limit: 12,
      }
      
      if (searchQuery) {
        params.search = searchQuery
      }
      
      const response = await client.get(`/api/catalog/games/${systemId}`, { params })
      const newGames = response.data.games || []
      
      if (append) {
        setGames(prev => [...prev, ...newGames])
      } else {
        setGames(newGames)
      }
      
      setHasMore(response.data.hasMore || false)
    } catch (err) {
      console.error('Error loading games:', err)
      setError('Failed to load games')
    } finally {
      setLoading(false)
    }
  }, [systemId, searchQuery])

  useEffect(() => {
    setPage(1)
    setGames([])
    setSelectedSubdirectory(null) // Reset filter when system or search changes
    loadGames(1, false)
  }, [systemId, searchQuery, loadGames])

  useEffect(() => {
    if (observerRef.current) {
      observerRef.current.disconnect()
    }

    observerRef.current = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && hasMore && !loading) {
          const nextPage = page + 1
          setPage(nextPage)
          loadGames(nextPage, true)
        }
      },
      { rootMargin: '100px' }
    )

    if (loadingRef.current) {
      observerRef.current.observe(loadingRef.current)
    }

    return () => {
      if (observerRef.current) {
        observerRef.current.disconnect()
      }
    }
  }, [hasMore, loading, page, loadGames])

  const handleDownload = async (gameId) => {
    try {
      const result = await addToQueue(gameId)
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

  if (loading && games.length === 0) {
    return <div className="loading">Loading games...</div>
  }

  if (error && games.length === 0) {
    return <div className="error">{error}</div>
  }

  const handleGameClick = (game) => {
    let gameId = game.id.replace(/^\.\//, '')
    if (gameId.startsWith(`${game.system}/`)) {
      gameId = gameId.substring(game.system.length + 1)
    }
    navigate(`/game/${game.system}/${encodeURIComponent(gameId)}`)
  }

  // Extract subdirectory from game ID
  const getGameSubdirectory = React.useCallback((gameId) => {
    // Remove leading ./
    let path = gameId.replace(/^\.\//, '')
    // Remove system prefix if present
    if (path.startsWith(`${systemId}/`)) {
      path = path.substring(systemId.length + 1)
    }
    // Get directory part (everything before the last /)
    const lastSlashIndex = path.lastIndexOf('/')
    if (lastSlashIndex === -1) {
      return null // No subdirectory, game is in root
    }
    return path.substring(0, lastSlashIndex)
  }, [systemId])

  // Group games by subdirectory and get unique subdirectories
  const subdirectories = React.useMemo(() => {
    const subdirSet = new Set()
    games.forEach(game => {
      const subdir = getGameSubdirectory(game.id)
      if (subdir !== null) {
        subdirSet.add(subdir)
      }
    })
    return Array.from(subdirSet).sort()
  }, [games, getGameSubdirectory])

  // Count games per subdirectory
  const subdirectoryCounts = React.useMemo(() => {
    const counts = {}
    games.forEach(game => {
      const subdir = getGameSubdirectory(game.id)
      const key = subdir || '(root)'
      counts[key] = (counts[key] || 0) + 1
    })
    return counts
  }, [games, getGameSubdirectory])

  // Filter games based on selected subdirectory
  const filteredGames = React.useMemo(() => {
    if (selectedSubdirectory === null) {
      return games
    }
    return games.filter(game => {
      const subdir = getGameSubdirectory(game.id)
      return subdir === selectedSubdirectory
    })
  }, [games, selectedSubdirectory, getGameSubdirectory])

  return (
    <div className="system-games">
      <div className="system-games-header">
        <div>
          <h1>{systemName}</h1>
          {searchQuery && <p>Search results for: "{searchQuery}"</p>}
        </div>
        <div className="view-toggle">
          <button
            className={`view-toggle-btn ${viewMode === 'grid' ? 'active' : ''}`}
            onClick={() => handleViewChange('grid')}
            title="Grid View"
            aria-label="Grid View"
          >
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
              <rect x="2" y="2" width="6" height="6" rx="1" stroke="currentColor" strokeWidth="1.5" fill="none"/>
              <rect x="12" y="2" width="6" height="6" rx="1" stroke="currentColor" strokeWidth="1.5" fill="none"/>
              <rect x="2" y="12" width="6" height="6" rx="1" stroke="currentColor" strokeWidth="1.5" fill="none"/>
              <rect x="12" y="12" width="6" height="6" rx="1" stroke="currentColor" strokeWidth="1.5" fill="none"/>
            </svg>
          </button>
          <button
            className={`view-toggle-btn ${viewMode === 'table' ? 'active' : ''}`}
            onClick={() => handleViewChange('table')}
            title="Table View"
            aria-label="Table View"
          >
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M2 4H18M2 8H18M2 12H18M2 16H18" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
              <path d="M2 4V16M6 4V16M10 4V16M14 4V16M18 4V16" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
            </svg>
          </button>
        </div>
      </div>

      {/* Subdirectory Filter Bar - only show if there are subdirectories */}
      {subdirectories.length > 0 && (
        <div className="subdirectory-filter-bar">
          <button
            className={`subdirectory-filter-btn ${selectedSubdirectory === null ? 'active' : ''}`}
            onClick={() => setSelectedSubdirectory(null)}
          >
            All
            {subdirectoryCounts['(root)'] && <span className="subdirectory-count">({games.length})</span>}
          </button>
          {subdirectories.map((subdir) => (
            <button
              key={subdir}
              className={`subdirectory-filter-btn ${selectedSubdirectory === subdir ? 'active' : ''}`}
              onClick={() => setSelectedSubdirectory(subdir)}
            >
              {subdir}
              <span className="subdirectory-count">({subdirectoryCounts[subdir] || 0})</span>
            </button>
          ))}
        </div>
      )}
      
      {games.length === 0 ? (
        <div className="no-games">No games found</div>
      ) : (
        <>
          {viewMode === 'grid' ? (
            <div className="games-grid">
              {filteredGames.map((game) => (
                <GameCard 
                  key={game.id} 
                  game={game} 
                  onDownload={handleDownload}
                />
              ))}
            </div>
          ) : (
            <div className="games-table-container">
              <table className="games-table">
                <thead>
                  <tr>
                    <th>Image</th>
                    <th>Game Name</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredGames.map((game) => {
                    // Get game image with priority: thumbnail > boxart > extra1 > image
                    const getGameImage = (game) => {
                      if (game.thumbnail) return getMediaUrl(game.thumbnail)
                      if (game.boxart) return getMediaUrl(game.boxart)
                      if (game.extra1) return getMediaUrl(game.extra1)
                      if (game.image) return getMediaUrl(game.image)
                      return '/assets/images/no-image.png'
                    }
                    const imageUrl = getGameImage(game)
                    let gameId = game.id.replace(/^\.\//, '')
                    if (gameId.startsWith(`${game.system}/`)) {
                      gameId = gameId.substring(game.system.length + 1)
                    }
                    
                    return (
                      <tr key={game.id} onClick={() => handleGameClick(game)} className="game-table-row">
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
                        <td className="game-actions-cell" onClick={(e) => e.stopPropagation()}>
                          {(isDownload || isFastDownload) && (
                            <button
                              className="download-btn"
                              onClick={(e) => {
                                e.stopPropagation()
                                handleDownload(game.id)
                              }}
                            >
                              Download
                            </button>
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
          
          {hasMore && (
            <div ref={loadingRef} className="load-more-trigger">
              {loading && <p>Loading more games...</p>}
            </div>
          )}
        </>
      )}
      <TokenSelectorDropdown
        isOpen={showTokenSelector}
        onClose={cancelTokenSelection}
        onSelect={handleTokenSelected}
      />
    </div>
  )
}

export default SystemGames

