import React, { useState, useEffect, useRef, useCallback } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import GameCard from './GameCard'
import TokenSelectorDropdown from '../TokenSelector/TokenSelectorDropdown'
import WarningModal from '../WarningModal/WarningModal'
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
  const [gamelistDate, setGamelistDate] = useState(null)
  const [viewMode, setViewMode] = useState('grid') // 'grid' or 'table'
  const [selectedSubdirectory, setSelectedSubdirectory] = useState(null) // null = all, or specific subdirectory
  const [subdirectoryCounts, setSubdirectoryCounts] = useState({}) // Pre-computed counts from backend
  const [selectedLetter, setSelectedLetter] = useState(null) // null = all, or specific letter (A-Z)
  const [showFavoritesOnly, setShowFavoritesOnly] = useState(false) // Filter to show only favorites
  const [sortByPlaycount, setSortByPlaycount] = useState(false) // Sort/filter by playcount
  const [sortByPlaytime, setSortByPlaytime] = useState(false) // Sort/filter by playtime
  const [nameFilter, setNameFilter] = useState('') // Filter by game name
  const [tableSortColumn, setTableSortColumn] = useState('name') // 'name', 'publisher', 'releaseDate'
  const [tableSortDirection, setTableSortDirection] = useState('asc') // 'asc' or 'desc'
  const observerRef = useRef(null)
  const loadingRef = useRef(null)
  const scrollRestoredRef = useRef(false)
  const gameElementsRef = useRef({}) // Store refs to game elements by game ID
  const navigate = useNavigate()
  const location = useLocation()
  const { addToQueue, handleTokenSelected, cancelTokenSelection, showTokenSelector, showOldClientWarning, setShowOldClientWarning } = useDownloadWithToken()
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
        const { subdirectory, letter, favorite, playcount, playtime, nameFilter } = JSON.parse(savedFilters)
        setSelectedSubdirectory(subdirectory)
        setSelectedLetter(letter)
        setShowFavoritesOnly(favorite || false)
        setSortByPlaycount(playcount || false)
        setSortByPlaytime(playtime || false)
        setNameFilter(nameFilter || '')
        setNameFilter(filters.nameFilter || '')
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
        letter: selectedLetter,
        favorite: showFavoritesOnly,
        playcount: sortByPlaycount,
        playtime: sortByPlaytime,
        nameFilter: nameFilter
      }))
    }
  }, [selectedSubdirectory, selectedLetter, showFavoritesOnly, sortByPlaycount, sortByPlaytime, nameFilter, getStorageKey])

  // Reset displayed count when filters change to show all filtered results
  useEffect(() => {
    if (filtersRestoredRef.current) {
      setDisplayedGamesCount(100) // Show more games when filters are applied
    }
  }, [sortByPlaycount, sortByPlaytime, showFavoritesOnly])

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

      let currentSystemVersion = propSystemVersion

      // Fetch system info to get version and gamelist date
      if (!currentSystemVersion) {
        try {
          const systemsResponse = await getSystems(catalogType)
          const systemInfo = systemsResponse.systems?.find(s => s.id === systemId)
          if (systemInfo?.version) {
            currentSystemVersion = systemInfo.version
            setSystemVersion(currentSystemVersion)
          }
          if (systemInfo?.gamelistDate) {
            setGamelistDate(systemInfo.gamelistDate)
          }
        } catch (err) {
          console.error('Error fetching system version:', err)
        }
      }

      // Fetch all games in one call with a very high limit
      const response = await getGames(systemId, 1, 10000, searchQuery || '', catalogType)
      const games = response.games || []

      // Get systemName from the first game (all games have the same systemName)
      if (games.length > 0 && games[0].systemName) {
        setSystemName(games[0].systemName)
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
      setShowFavoritesOnly(false) // Reset favorite filter when system or search changes
      setSortByPlaycount(false) // Reset playcount filter when system or search changes
      setSortByPlaytime(false) // Reset playtime filter when system or search changes
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

    // Apply playcount filter/sort FIRST (before letter/subdirectory filters)
    // This ensures we get all games with stats, then filter by letter/subdirectory
    if (sortByPlaycount) {
      // Helper function to safely parse playcount
      const getPlaycount = (game) => {
        if (game.playcount == null) return 0
        if (typeof game.playcount === 'number') return game.playcount
        const parsed = parseInt(game.playcount, 10)
        return isNaN(parsed) ? 0 : parsed
      }

      filtered = filtered
        .filter(game => {
          const playcount = getPlaycount(game)
          return playcount > 0
        })
        .sort((a, b) => {
          const playcountA = getPlaycount(a)
          const playcountB = getPlaycount(b)
          return playcountB - playcountA // Descending order
        })
    }

    // Apply playtime filter/sort FIRST (before letter/subdirectory filters)
    if (sortByPlaytime) {
      // Helper function to safely parse gametime
      const getGametime = (game) => {
        if (game.gametime == null) return 0
        if (typeof game.gametime === 'number') return game.gametime
        const parsed = parseInt(game.gametime, 10)
        return isNaN(parsed) ? 0 : parsed
      }

      filtered = filtered
        .filter(game => {
          const gametime = getGametime(game)
          return gametime > 0
        })
        .sort((a, b) => {
          const gametimeA = getGametime(a)
          const gametimeB = getGametime(b)
          return gametimeB - gametimeA // Descending order
        })
    }

    // Now apply subdirectory filter AFTER playcount/playtime
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

    // Apply letter filter AFTER playcount/playtime
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

    // Apply favorite filter AFTER playcount/playtime
    if (showFavoritesOnly) {
      filtered = filtered.filter(game => game.favorite === 'true')
    }

    // Apply name filter (case-insensitive contains match)
    if (nameFilter && nameFilter.trim()) {
      const filterLower = nameFilter.toLowerCase().trim()
      filtered = filtered.filter(game => {
        const gameName = (game.name || '').toLowerCase()
        return gameName.includes(filterLower)
      })
    }

    return filtered
  }, [allGames, selectedSubdirectory, selectedLetter, showFavoritesOnly, sortByPlaycount, sortByPlaytime, nameFilter, getGameSubdirectory])

  // Format release date to show only year
  const formatReleaseYear = (dateStr) => {
    if (!dateStr) return ''
    // Format: YYYYMMDDTHHMMSS or YYYYMMDD -> YYYY
    if (dateStr.length >= 4) {
      const year = dateStr.substring(0, 4)
      // Validate it's a valid year (1900-2100)
      const yearNum = parseInt(year)
      if (yearNum >= 1900 && yearNum <= 2100) {
        return year
      }
    }
    return ''
  }

  // Format gametime from minutes to readable format
  const formatGametime = (minutes) => {
    if (!minutes || minutes === 0) return null
    const hours = Math.floor(minutes / 60)
    const mins = minutes % 60
    if (hours > 0 && mins > 0) {
      return `${hours}h ${mins}m`
    } else if (hours > 0) {
      return `${hours}h`
    } else {
      return `${mins}m`
    }
  }

  // Handle both string and number types for playcount/gametime
  const getPlaycount = (game) => {
    if (game.playcount == null) return 0
    if (typeof game.playcount === 'number') return game.playcount
    const parsed = parseInt(game.playcount, 10)
    return isNaN(parsed) ? 0 : parsed
  }

  const getGametime = (game) => {
    if (game.gametime == null) return 0
    if (typeof game.gametime === 'number') return game.gametime
    const parsed = parseInt(game.gametime, 10)
    return isNaN(parsed) ? 0 : parsed
  }

  // Sort games for table view if needed
  const sortedGamesForTable = React.useMemo(() => {
    if (viewMode !== 'table') {
      return filteredGames
    }

    // Sort by table sort column
    const sorted = [...filteredGames].sort((a, b) => {
      let compareResult = 0

      if (tableSortColumn === 'name') {
        const nameA = (a.name || '').toLowerCase()
        const nameB = (b.name || '').toLowerCase()
        compareResult = nameA.localeCompare(nameB)
      } else if (tableSortColumn === 'publisher') {
        const pubA = (a.publisher || 'Unknown').toLowerCase()
        const pubB = (b.publisher || 'Unknown').toLowerCase()
        compareResult = pubA.localeCompare(pubB)
      } else if (tableSortColumn === 'releaseDate') {
        const dateA = a.releasedate || 'Unknown'
        const dateB = b.releasedate || 'Unknown'
        if (dateA === 'Unknown' && dateB === 'Unknown') {
          compareResult = 0
        } else if (dateA === 'Unknown') {
          compareResult = 1  // Unknown goes last
        } else if (dateB === 'Unknown') {
          compareResult = -1  // Unknown goes last
        } else {
          // Extract year from releasedate (format: YYYYMMDDTHHMMSS or YYYYMMDD)
          const yearA = dateA.length >= 4 ? parseInt(dateA.substring(0, 4)) : 0
          const yearB = dateB.length >= 4 ? parseInt(dateB.substring(0, 4)) : 0
          if (yearA && yearB) {
            compareResult = yearA - yearB
          } else {
            compareResult = dateA.localeCompare(dateB)
          }
        }
      } else if (tableSortColumn === 'playcount') {
        const playcountA = getPlaycount(a)
        const playcountB = getPlaycount(b)
        compareResult = playcountA - playcountB
      } else if (tableSortColumn === 'gametime') {
        const gametimeA = getGametime(a)
        const gametimeB = getGametime(b)
        compareResult = gametimeA - gametimeB
      }

      return tableSortDirection === 'desc' ? -compareResult : compareResult
    })

    return sorted
  }, [filteredGames, viewMode, tableSortColumn, tableSortDirection])

  const handleTableSort = (column) => {
    if (tableSortColumn === column) {
      // Toggle direction if clicking the same column
      setTableSortDirection(tableSortDirection === 'asc' ? 'desc' : 'asc')
    } else {
      // New column, default to ascending
      setTableSortColumn(column)
      setTableSortDirection('asc')
    }
  }

  // Get displayed games (frontend pagination)
  const displayedGames = React.useMemo(() => {
    const gamesToDisplay = viewMode === 'table' ? sortedGamesForTable : filteredGames
    return gamesToDisplay.slice(0, displayedGamesCount)
  }, [filteredGames, sortedGamesForTable, displayedGamesCount, viewMode])

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

  // Get unique subdirectories from backend counts (excluding root and categories with only 1 game) - must be before early returns
  const subdirectories = React.useMemo(() => {
    return Object.keys(subdirectoryCounts)
      .filter(key => key !== '(root)')
      .filter(key => (subdirectoryCounts[key] || 0) > 1) // Only show categories with more than 1 game
      .sort()
  }, [subdirectoryCounts])

  // Generate letters # and A-Z for filter
  const letters = React.useMemo(() => {
    return ['#', ...Array.from({ length: 26 }, (_, i) => String.fromCharCode(65 + i))] // #, A-Z
  }, [])

  const handleDownload = async (game) => {
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

  const handleGameClick = (game) => {
    // Save the game ID so we can scroll to it when coming back
    const viewedGameKey = getStorageKey('viewedGame')
    localStorage.setItem(viewedGameKey, game.id)

    // Save ordered list of game IDs for prev/next navigation in GameDetails
    const navList = (viewMode === 'table' ? sortedGamesForTable : filteredGames).map(g => g.id)
    sessionStorage.setItem(`gameNavList_${systemId}`, JSON.stringify(navList))

    let gameId = game.id.replace(/^\.\//, '')
    if (gameId.startsWith(`${game.system}/`)) {
      gameId = gameId.substring(game.system.length + 1)
    }
    navigate(`/game/${game.system}/${encodeURIComponent(gameId)}`, {
      state: { fromSystemGames: true, systemId }
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
      <WarningModal
        isOpen={showOldClientWarning}
        onClose={() => setShowOldClientWarning(false)}
        title="Update Required"
        message="Your client version is too old. Please update your client to download games."
      />
      <div className="system-games-header">
        <div className="system-games-title-section">
          <h1>{systemName}</h1>
          {catalogType === 'wip' && gamelistDate && (
            <span className="system-gamelist-date">Updated: {gamelistDate}</span>
          )}
          <button
            className={`favorite-filter-btn ${showFavoritesOnly ? 'active' : ''}`}
            onClick={() => setShowFavoritesOnly(!showFavoritesOnly)}
            title={showFavoritesOnly ? 'Show all games' : 'Show favorites only'}
            aria-label={showFavoritesOnly ? 'Show all games' : 'Show favorites only'}
          >
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
              {showFavoritesOnly ? (
                <path d="M10 15L4.5 18L5.5 11.5L1 7L7.5 6.25L10 0L12.5 6.25L19 7L14.5 11.5L15.5 18L10 15Z" fill="currentColor" />
              ) : (
                <path d="M10 15L4.5 18L5.5 11.5L1 7L7.5 6.25L10 0L12.5 6.25L19 7L14.5 11.5L15.5 18L10 15Z" stroke="currentColor" strokeWidth="1.5" fill="none" />
              )}
            </svg>
          </button>
          <button
            className={`playcount-filter-btn ${sortByPlaycount ? 'active' : ''}`}
            onClick={() => {
              if (sortByPlaycount) {
                setSortByPlaycount(false)
              } else {
                setSortByPlaycount(true)
                setSortByPlaytime(false) // Only one can be active at a time
              }
            }}
            title={sortByPlaycount ? 'Show all games' : 'Sort by playcount (highest first)'}
            aria-label={sortByPlaycount ? 'Show all games' : 'Sort by playcount (highest first)'}
          >
            <span>Playcount</span>
          </button>
          <button
            className={`playtime-filter-btn ${sortByPlaytime ? 'active' : ''}`}
            onClick={() => {
              if (sortByPlaytime) {
                setSortByPlaytime(false)
              } else {
                setSortByPlaytime(true)
                setSortByPlaycount(false) // Only one can be active at a time
              }
            }}
            title={sortByPlaytime ? 'Show all games' : 'Sort by playtime (highest first)'}
            aria-label={sortByPlaytime ? 'Show all games' : 'Sort by playtime (highest first)'}
          >
            <span>Playtime</span>
          </button>
          <div className="name-filter-container">
            <input
              id="name-filter-input"
              type="text"
              className="name-filter-input"
              placeholder="Filter by name..."
              value={nameFilter}
              onChange={(e) => setNameFilter(e.target.value)}
            />
          </div>
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
              <rect x="2" y="2" width="6" height="6" rx="1" stroke="currentColor" strokeWidth="1.5" fill="none" />
              <rect x="12" y="2" width="6" height="6" rx="1" stroke="currentColor" strokeWidth="1.5" fill="none" />
              <rect x="2" y="12" width="6" height="6" rx="1" stroke="currentColor" strokeWidth="1.5" fill="none" />
              <rect x="12" y="12" width="6" height="6" rx="1" stroke="currentColor" strokeWidth="1.5" fill="none" />
            </svg>
          </button>
          <button
            className={`view-toggle-btn ${viewMode === 'table' ? 'active' : ''}`}
            onClick={() => handleViewChange('table')}
            title="Table View"
            aria-label="Table View"
          >
            <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M2 4H18M2 8H18M2 12H18M2 16H18" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              <path d="M2 4V16M6 4V16M10 4V16M14 4V16M18 4V16" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
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
                    onDownload={() => handleDownload(game)}
                    onGameClick={handleGameClick}
                    showSystemName={false}
                    catalogType={catalogType}
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
                    <th
                      className="sortable"
                      onClick={() => handleTableSort('name')}
                      style={{ cursor: 'pointer' }}
                    >
                      Game Name {tableSortColumn === 'name' && (tableSortDirection === 'asc' ? '↑' : '↓')}
                    </th>
                    <th
                      className="sortable"
                      onClick={() => handleTableSort('publisher')}
                      style={{ cursor: 'pointer' }}
                    >
                      Publisher {tableSortColumn === 'publisher' && (tableSortDirection === 'asc' ? '↑' : '↓')}
                    </th>
                    <th
                      className="sortable"
                      onClick={() => handleTableSort('releaseDate')}
                      style={{ cursor: 'pointer' }}
                    >
                      Year {tableSortColumn === 'releaseDate' && (tableSortDirection === 'asc' ? '↑' : '↓')}
                    </th>
                    <th
                      className="sortable"
                      onClick={() => handleTableSort('playcount')}
                      style={{ cursor: 'pointer' }}
                    >
                      Plays {tableSortColumn === 'playcount' && (tableSortDirection === 'asc' ? '↑' : '↓')}
                    </th>
                    <th
                      className="sortable"
                      onClick={() => handleTableSort('gametime')}
                      style={{ cursor: 'pointer' }}
                    >
                      Playtime {tableSortColumn === 'gametime' && (tableSortDirection === 'asc' ? '↑' : '↓')}
                    </th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {displayedGames.map((game) => {
                    // Backend pre-computes catalog_image, but check fallbacks just in case
                    const bestImage = game.catalog_image || game.thumbnail || game.boxart || game.image
                    const imageUrl = bestImage ? getMediaUrl(bestImage, catalogType) : '/assets/images/no-image.png'
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
                        <td className="game-publisher-cell">
                          {game.publisher || '-'}
                        </td>
                        <td className="game-releaseyear-cell">
                          {formatReleaseYear(game.releasedate) || '-'}
                        </td>
                        <td className="game-playcount-cell">
                          {getPlaycount(game) > 0 ? getPlaycount(game) : '-'}
                        </td>
                        <td className="game-gametime-cell">
                          {formatGametime(getGametime(game)) || '-'}
                        </td>
                        <td className="game-actions-cell" onClick={(e) => e.stopPropagation()}>
                          {(isDownload || isFastDownload) && (
                            <button
                              className="download-btn"
                              onClick={(e) => {
                                e.stopPropagation()
                                handleDownload(game)
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

