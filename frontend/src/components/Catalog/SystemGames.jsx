import React, { useState, useEffect, useRef, useCallback } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import GameCard from './GameCard'
import TokenSelectorDropdown from '../TokenSelector/TokenSelectorDropdown'
import { useDownloadWithToken } from '../../hooks/useDownloadWithToken'
import { useAuth } from '../../context/AuthContext'
import { useCatalog } from '../../context/CatalogContext'
import { getMediaUrl } from '../../utils/constants'
import { getGames, getSystems } from '../../api/catalog'
import './SystemGames.css'

const SystemGames = ({ systemId, systemName: propSystemName, searchQuery = '', systemVersion: propSystemVersion }) => {
  const { catalogType } = useCatalog()
  const [allGames, setAllGames] = useState([]) // All games loaded from API
  const [displayedGamesCount, setDisplayedGamesCount] = useState(24) // Number of games to display (frontend pagination)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  // systemName is derived from games response (all games have the same systemName)
  const [systemName, setSystemName] = useState(propSystemName || '')
  const [systemVersion, setSystemVersion] = useState(propSystemVersion || null)
  const [viewMode, setViewMode] = useState('grid') // 'grid' or 'table'
  const [selectedSubdirectory, setSelectedSubdirectory] = useState(null) // null = all, or specific subdirectory
  const [subdirectoryCounts, setSubdirectoryCounts] = useState({}) // Pre-computed counts from backend
  const [selectedLetter, setSelectedLetter] = useState(null) // null = all, or specific letter (A-Z)
  const observerRef = useRef(null)
  const loadingRef = useRef(null)
  const scrollRestoredRef = useRef(false)
  const gameElementsRef = useRef({}) // Store refs to game elements by game ID
  const navigate = useNavigate()
  const location = useLocation()
  const { addToQueue, handleTokenSelected, cancelTokenSelection, showTokenSelector } = useDownloadWithToken()
  const { isDownload, isFastDownload } = useAuth()

  // Get storage key for this system/search combination
  const getStorageKey = useCallback((suffix) => {
    return `systemGames_${suffix}_${systemId}_${searchQuery || 'no-search'}`
  }, [systemId, searchQuery])


  // Load view preference from localStorage
  useEffect(() => {
    const savedView = localStorage.getItem('systemGamesViewMode')
    if (savedView === 'table' || savedView === 'grid') {
      setViewMode(savedView)
    }
  }, [])

  // Restore filter state from localStorage on mount (only once per system/search)
  const filtersRestoredRef = useRef(false)
  useEffect(() => {
    const filtersKey = getStorageKey('filters')
    const savedFilters = localStorage.getItem(filtersKey)
    if (savedFilters && !filtersRestoredRef.current) {
      try {
        const { subdirectory, letter } = JSON.parse(savedFilters)
        setSelectedSubdirectory(subdirectory)
        setSelectedLetter(letter)
        filtersRestoredRef.current = true
      } catch (e) {
        console.error('Error restoring filters:', e)
        filtersRestoredRef.current = true
      }
    } else if (!savedFilters) {
      filtersRestoredRef.current = true
    }
  }, [systemId, searchQuery, getStorageKey])

  // Save filter state to localStorage whenever it changes
  useEffect(() => {
    // Only save if filters have been restored (to avoid overwriting with null on initial mount)
    if (filtersRestoredRef.current) {
      const filtersKey = getStorageKey('filters')
      localStorage.setItem(filtersKey, JSON.stringify({
        subdirectory: selectedSubdirectory,
        letter: selectedLetter
      }))
    }
  }, [selectedSubdirectory, selectedLetter, getStorageKey])

  // Save view preference to localStorage
  const handleViewChange = (mode) => {
    setViewMode(mode)
    localStorage.setItem('systemGamesViewMode', mode)
  }

  // Track if we're currently loading to prevent duplicate calls
  const isLoadingRef = useRef(false)
  const lastLoadKeyRef = useRef('') // Track what we last loaded to prevent duplicate loads

  // Load all games for the system in one call
  const loadAllGames = useCallback(async () => {
    // Create a unique key for this load request (include catalogType)
    const loadKey = `${systemId}_${searchQuery || 'no-search'}_${catalogType}`
    
    // Prevent duplicate calls (especially in React StrictMode)
    if (isLoadingRef.current && lastLoadKeyRef.current === loadKey) {
      return
    }
    
    try {
      isLoadingRef.current = true
      lastLoadKeyRef.current = loadKey
      setLoading(true)
      setError(null)
      setDisplayedGamesCount(24) // Reset displayed count
      
      // Fetch all games in one call with a very high limit
      const response = await getGames(systemId, 1, 10000, searchQuery || '', catalogType)
      const games = response.games || []
      
      // Get systemName from the first game (all games have the same systemName)
      if (games.length > 0 && games[0].systemName) {
        setSystemName(games[0].systemName)
      }
      
      // Fetch system info to get version if not provided as prop
      if (!propSystemVersion) {
        try {
          const systemsResponse = await getSystems(catalogType)
          const systemInfo = systemsResponse.systems?.find(s => s.id === systemId)
          if (systemInfo?.version) {
            setSystemVersion(systemInfo.version)
          }
        } catch (err) {
          console.error('Error fetching system version:', err)
        }
      }
      
      // Update subdirectory counts from backend
      if (response.subdirectory_counts) {
        setSubdirectoryCounts(response.subdirectory_counts)
      }
      
      setAllGames(games)
    } catch (err) {
      console.error('Error loading games:', err)
      setError('Failed to load games')
      lastLoadKeyRef.current = '' // Reset on error so it can retry
    } finally {
      setLoading(false)
      isLoadingRef.current = false
    }
  }, [systemId, searchQuery, catalogType, propSystemVersion])

  // Scroll to the viewed game after games are loaded and filtered
  const isRestoringScrollRef = useRef(false)
  
  useEffect(() => {
    if (!loading && allGames.length > 0 && !scrollRestoredRef.current) {
      const viewedGameKey = getStorageKey('viewedGame')
      const viewedGameId = localStorage.getItem(viewedGameKey)
      
      if (viewedGameId) {
        // Check if the viewed game is in the loaded games
        const gameExists = allGames.some(game => game.id === viewedGameId)
        
        if (gameExists) {
          // Make sure the game is displayed (increase displayed count if needed)
          // Increase displayed count to ensure the game is visible after filtering
          if (displayedGamesCount < 100) {
            setDisplayedGamesCount(100) // Show more games to ensure the target is visible
          }
          
          // Game is loaded, wait for DOM to be fully rendered
          isRestoringScrollRef.current = true
          requestAnimationFrame(() => {
            setTimeout(() => {
              // Find the game element in the filtered games
              const gameElement = gameElementsRef.current[viewedGameId]
              if (gameElement) {
                // Scroll to the game element with some offset for sticky header
                const headerOffset = 180 // Account for sticky header and filters
                const elementPosition = gameElement.getBoundingClientRect().top
                const offsetPosition = elementPosition + window.pageYOffset - headerOffset
                
                window.scrollTo({
                  top: offsetPosition,
                  behavior: 'smooth'
                })
                
                // Clear the viewed game from storage after scrolling
                localStorage.removeItem(viewedGameKey)
              }
              scrollRestoredRef.current = true
              isRestoringScrollRef.current = false
            }, 800) // Increased delay to ensure DOM is ready
          })
        } else {
          // Game not found
          scrollRestoredRef.current = true
          isRestoringScrollRef.current = false
          localStorage.removeItem(viewedGameKey) // Clean up
        }
      } else {
        scrollRestoredRef.current = true
      }
    }
  }, [loading, allGames.length, displayedGamesCount, selectedSubdirectory, selectedLetter, getStorageKey])

  // Track previous systemId and searchQuery to detect actual changes
  const prevSystemIdRef = useRef(systemId)
  const prevSearchQueryRef = useRef(searchQuery)
  const isInitialMountRef = useRef(true)

  useEffect(() => {
    const oldSystemId = prevSystemIdRef.current
    const oldSearchQuery = prevSearchQueryRef.current
    const systemChanged = oldSystemId !== systemId
    const searchChanged = oldSearchQuery !== searchQuery
    
    // On initial mount, don't reset filters (they'll be restored from sessionStorage)
    if (isInitialMountRef.current) {
      isInitialMountRef.current = false
      prevSystemIdRef.current = systemId
      prevSearchQueryRef.current = searchQuery
      setAllGames([])
      setDisplayedGamesCount(24)
      scrollRestoredRef.current = false
      isRestoringScrollRef.current = false
      loadAllGames()
      return
    }
    
    prevSystemIdRef.current = systemId
    prevSearchQueryRef.current = searchQuery

    setAllGames([])
    setDisplayedGamesCount(24)
    scrollRestoredRef.current = false // Reset scroll restoration flag
    isRestoringScrollRef.current = false // Reset scroll restoration state
    
    // Only reset filters if system or search actually changed
    // (not when just remounting after coming back from game detail)
    if (systemChanged || searchChanged) {
      setSelectedSubdirectory(null) // Reset filter when system or search changes
      setSelectedLetter(null) // Reset letter filter when system or search changes
      filtersRestoredRef.current = false // Allow filters to be restored for new system/search
      // Clear saved filters for old system/search
      const oldFiltersKey = `systemGames_filters_${oldSystemId}_${oldSearchQuery || 'no-search'}`
      localStorage.removeItem(oldFiltersKey)
    }
    
    loadAllGames()
  }, [systemId, searchQuery, loadAllGames])

  // Extract subdirectory from game ID - must be before filteredGames
  const getGameSubdirectory = useCallback((gameId) => {
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

  // Filter games based on selected subdirectory and letter
  const filteredGames = React.useMemo(() => {
    let filtered = allGames
    
    // Apply subdirectory filter
    if (selectedSubdirectory !== null) {
      // Special value "(root)" means show only root directory games
      if (selectedSubdirectory === '(root)') {
        filtered = filtered.filter(game => {
          const subdir = getGameSubdirectory(game.id)
          return subdir === null // Root directory games have no subdirectory
        })
      } else {
        filtered = filtered.filter(game => {
          const subdir = getGameSubdirectory(game.id)
          return subdir === selectedSubdirectory
        })
      }
    }
    
    // Apply letter filter
    if (selectedLetter !== null) {
      filtered = filtered.filter(game => {
        const firstChar = game.name?.charAt(0).toUpperCase() || ''
        if (selectedLetter === '#') {
          // Show games that don't start with a letter
          return !firstChar.match(/[A-Z]/)
        } else {
          // Show games that start with the selected letter
          return firstChar === selectedLetter
        }
      })
    }
    
    return filtered
  }, [allGames, selectedSubdirectory, selectedLetter, getGameSubdirectory])

  // Get displayed games (frontend pagination)
  const displayedGames = React.useMemo(() => {
    return filteredGames.slice(0, displayedGamesCount)
  }, [filteredGames, displayedGamesCount])

  const hasMoreGames = filteredGames.length > displayedGamesCount

  // Frontend-side infinite scroll - load more games from already loaded data
  useEffect(() => {
    if (observerRef.current) {
      observerRef.current.disconnect()
    }

    // Don't set up infinite scroll observer if we're restoring scroll position
    if (isRestoringScrollRef.current) {
      return
    }

    observerRef.current = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && hasMoreGames && !loading && !isRestoringScrollRef.current) {
          // Load 24 more games (frontend pagination)
          setDisplayedGamesCount(prev => prev + 24)
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
  }, [hasMoreGames, loading])

  // Get unique subdirectories from backend counts (excluding root) - must be before early returns
  const subdirectories = React.useMemo(() => {
    return Object.keys(subdirectoryCounts)
      .filter(key => key !== '(root)')
      .sort()
  }, [subdirectoryCounts])
  
  // Generate letters # and A-Z for filter
  const letters = React.useMemo(() => {
    return ['#', ...Array.from({ length: 26 }, (_, i) => String.fromCharCode(65 + i))] // #, A-Z
  }, [])

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

  const handleGameClick = (game) => {
    // Save the game ID so we can scroll to it when coming back
    const viewedGameKey = getStorageKey('viewedGame')
    localStorage.setItem(viewedGameKey, game.id)
    
    let gameId = game.id.replace(/^\.\//, '')
    if (gameId.startsWith(`${game.system}/`)) {
      gameId = gameId.substring(game.system.length + 1)
    }
    navigate(`/game/${game.system}/${encodeURIComponent(gameId)}`, {
      state: { fromSystemGames: true }
    })
  }

  // Early returns must come AFTER all hooks
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
          <h1>{systemName}</h1>
          {catalogType === 'releases' && systemVersion && (
            <span className="system-version">version {systemVersion}</span>
          )}
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

      {/* Filters Container - Sticky */}
      <div className="filters-container">
        {/* Subdirectory Filter Bar - only show if there are subdirectories */}
        {subdirectories.length > 0 && (
          <div className="subdirectory-filter-bar">
            <button
              className={`subdirectory-filter-btn ${selectedSubdirectory === null ? 'active' : ''}`}
              onClick={() => setSelectedSubdirectory(null)}
            >
              All
              {subdirectoryCounts['(root)'] && <span className="subdirectory-count">({Object.values(subdirectoryCounts).reduce((sum, count) => sum + count, 0)})</span>}
            </button>
            {subdirectoryCounts['(root)'] && subdirectoryCounts['(root)'] > 0 && (
              <button
                className={`subdirectory-filter-btn ${selectedSubdirectory === '(root)' ? 'active' : ''}`}
                onClick={() => setSelectedSubdirectory('(root)')}
              >
                Main
                <span className="subdirectory-count">({subdirectoryCounts['(root)'] || 0})</span>
              </button>
            )}
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

        {/* Letter Filter Bar */}
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
      
      {allGames.length === 0 ? (
        <div className="no-games">No games found</div>
      ) : (
        <>
          {viewMode === 'grid' ? (
            <div className="games-grid">
              {displayedGames.map((game) => (
                <div
                  key={game.id}
                  ref={(el) => {
                    if (el) {
                      gameElementsRef.current[game.id] = el
                    } else {
                      delete gameElementsRef.current[game.id]
                    }
                  }}
                >
                  <GameCard 
                    game={game} 
                    onDownload={handleDownload}
                    onGameClick={handleGameClick}
                  />
                </div>
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
                  {displayedGames.map((game) => {
                    // Backend now returns the selected image in the 'image' field (priority: thumbnail > boxart > extra1 > image)
                    const imageUrl = game.image ? getMediaUrl(game.image) : '/assets/images/no-image.png'
                    let gameId = game.id.replace(/^\.\//, '')
                    if (gameId.startsWith(`${game.system}/`)) {
                      gameId = gameId.substring(game.system.length + 1)
                    }
                    
                    return (
                      <tr
                        key={game.id}
                        ref={(el) => {
                          if (el) {
                            gameElementsRef.current[game.id] = el
                          } else {
                            delete gameElementsRef.current[game.id]
                          }
                        }}
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
          
          {hasMoreGames && (
            <div ref={loadingRef} className="load-more-trigger">
              <p>Loading more games...</p>
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

