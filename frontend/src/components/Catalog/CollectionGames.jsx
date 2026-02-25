import React, { useState, useEffect, useRef, useCallback } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import GameCard from './GameCard'
import { useDownloadWithToken } from '../../hooks/useDownloadWithToken'
import WarningModal from '../WarningModal/WarningModal'
import { useAuth } from '../../context/AuthContext'
import { useCatalog } from '../../context/CatalogContext'
import { getCollectionGames } from '../../api/collections'
import { getMediaUrl } from '../../utils/constants'
import './SystemGames.css' // We can reuse the same layout classes

const CollectionGames = ({ collectionId, collectionName: propCollectionName, searchQuery = '' }) => {
    const { catalogType } = useCatalog()
    const [allGames, setAllGames] = useState([])
    const [displayedGamesCount, setDisplayedGamesCount] = useState(24)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState(null)

    // Format collection name for display instead of needing it passed down
    const defaultName = collectionId.replace(/^custom-/, '').replace(/-/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
    const [collectionName, setCollectionName] = useState(propCollectionName || defaultName)

    const [viewMode, setViewMode] = useState('grid')
    const [selectedLetter, setSelectedLetter] = useState(null)
    const [showFavoritesOnly, setShowFavoritesOnly] = useState(false)
    const [sortByPlaycount, setSortByPlaycount] = useState(false)
    const [sortByPlaytime, setSortByPlaytime] = useState(false)
    const [nameFilter, setNameFilter] = useState('')
    const [tableSortColumn, setTableSortColumn] = useState('name')
    const [tableSortDirection, setTableSortDirection] = useState('asc')

    const observerRef = useRef(null)
    const loadingRef = useRef(null)
    const scrollRestoredRef = useRef(false)
    const gameElementsRef = useRef({})
    const navigate = useNavigate()
    const location = useLocation()

    const { addToQueue, showOldClientWarning, setShowOldClientWarning } = useDownloadWithToken()
    const { isDownload, isFastDownload } = useAuth()

    // Get storage key
    const getStorageKey = useCallback((suffix) => {
        return `collectionGames_${suffix}_${collectionId}_${searchQuery || 'no-search'}`
    }, [collectionId, searchQuery])

    // Load view preference from localStorage
    useEffect(() => {
        const savedView = localStorage.getItem('collectionGamesViewMode')
        if (savedView === 'table' || savedView === 'grid') {
            setViewMode(savedView)
        }
    }, [])

    const filtersRestoredRef = useRef(false)
    useEffect(() => {
        const filtersKey = getStorageKey('filters')
        const savedFilters = localStorage.getItem(filtersKey)
        if (savedFilters && !filtersRestoredRef.current) {
            try {
                const filters = JSON.parse(savedFilters)
                setSelectedLetter(filters.letter)
                setShowFavoritesOnly(filters.favorite || false)
                setSortByPlaycount(filters.playcount || false)
                setSortByPlaytime(filters.playtime || false)
                setNameFilter(filters.nameFilter || '')
                filtersRestoredRef.current = true
            } catch (e) {
                console.error('Error restoring filters:', e)
                filtersRestoredRef.current = true
            }
        } else if (!savedFilters) {
            filtersRestoredRef.current = true
        }
    }, [collectionId, searchQuery, getStorageKey])

    useEffect(() => {
        if (filtersRestoredRef.current) {
            const filtersKey = getStorageKey('filters')
            localStorage.setItem(filtersKey, JSON.stringify({
                letter: selectedLetter,
                favorite: showFavoritesOnly,
                playcount: sortByPlaycount,
                playtime: sortByPlaytime,
                nameFilter: nameFilter
            }))
        }
    }, [selectedLetter, showFavoritesOnly, sortByPlaycount, sortByPlaytime, nameFilter, getStorageKey])

    useEffect(() => {
        if (filtersRestoredRef.current) {
            setDisplayedGamesCount(100)
        }
    }, [sortByPlaycount, sortByPlaytime, showFavoritesOnly])

    const handleViewChange = (mode) => {
        setViewMode(mode)
        localStorage.setItem('collectionGamesViewMode', mode)
    }

    const isLoadingRef = useRef(false)
    const lastLoadKeyRef = useRef('')

    const loadAllGames = useCallback(async () => {
        const loadKey = `${collectionId}_${searchQuery || 'no-search'}_${catalogType}`

        if (isLoadingRef.current && lastLoadKeyRef.current === loadKey) {
            return
        }

        try {
            isLoadingRef.current = true
            lastLoadKeyRef.current = loadKey
            setLoading(true)
            setError(null)
            setDisplayedGamesCount(24)

            const response = await getCollectionGames(collectionId, 1, 10000, searchQuery || '', catalogType)
            const games = response.games || []

            setAllGames(games)
        } catch (err) {
            console.error('Error loading games:', err)
            setError('Failed to load games')
            lastLoadKeyRef.current = ''
        } finally {
            setLoading(false)
            isLoadingRef.current = false
        }
    }, [collectionId, searchQuery, catalogType])

    const isRestoringScrollRef = useRef(false)

    useEffect(() => {
        if (!loading && allGames.length > 0 && !scrollRestoredRef.current) {
            const viewedGameKey = getStorageKey('viewedGame')
            const viewedGameId = localStorage.getItem(viewedGameKey)

            if (viewedGameId) {
                const gameExists = allGames.some(game => game.id === viewedGameId)

                if (gameExists) {
                    if (displayedGamesCount < 100) {
                        setDisplayedGamesCount(100)
                    }

                    isRestoringScrollRef.current = true
                    requestAnimationFrame(() => {
                        setTimeout(() => {
                            const gameElement = gameElementsRef.current[viewedGameId]
                            if (gameElement) {
                                const headerOffset = 180
                                const elementPosition = gameElement.getBoundingClientRect().top
                                const offsetPosition = elementPosition + window.pageYOffset - headerOffset

                                window.scrollTo({
                                    top: offsetPosition,
                                    behavior: 'smooth'
                                })

                                localStorage.removeItem(viewedGameKey)
                            }
                            scrollRestoredRef.current = true
                            isRestoringScrollRef.current = false
                        }, 800)
                    })
                } else {
                    scrollRestoredRef.current = true
                    isRestoringScrollRef.current = false
                    localStorage.removeItem(viewedGameKey)
                }
            } else {
                scrollRestoredRef.current = true
            }
        }
    }, [loading, allGames.length, displayedGamesCount, selectedLetter, getStorageKey])

    const prevCollectionIdRef = useRef(collectionId)
    const prevSearchQueryRef = useRef(searchQuery)
    const isInitialMountRef = useRef(true)

    useEffect(() => {
        const oldCollectionId = prevCollectionIdRef.current
        const oldSearchQuery = prevSearchQueryRef.current
        const collectionChanged = oldCollectionId !== collectionId
        const searchChanged = oldSearchQuery !== searchQuery

        if (isInitialMountRef.current) {
            isInitialMountRef.current = false
            prevCollectionIdRef.current = collectionId
            prevSearchQueryRef.current = searchQuery
            setAllGames([])
            setDisplayedGamesCount(24)
            scrollRestoredRef.current = false
            isRestoringScrollRef.current = false
            loadAllGames()
            return
        }

        prevCollectionIdRef.current = collectionId
        prevSearchQueryRef.current = searchQuery

        setAllGames([])
        setDisplayedGamesCount(24)
        scrollRestoredRef.current = false
        isRestoringScrollRef.current = false

        if (collectionChanged || searchChanged) {
            setSelectedLetter(null)
            setShowFavoritesOnly(false)
            setSortByPlaycount(false)
            setSortByPlaytime(false)
            filtersRestoredRef.current = false
            const oldFiltersKey = `collectionGames_filters_${oldCollectionId}_${oldSearchQuery || 'no-search'}`
            localStorage.removeItem(oldFiltersKey)
        }

        loadAllGames()
    }, [collectionId, searchQuery, loadAllGames])

    const filteredGames = React.useMemo(() => {
        let filtered = allGames

        if (sortByPlaycount) {
            const getPlaycount = (game) => {
                if (game.playcount == null) return 0
                if (typeof game.playcount === 'number') return game.playcount
                const parsed = parseInt(game.playcount, 10)
                return isNaN(parsed) ? 0 : parsed
            }

            filtered = filtered
                .filter(game => getPlaycount(game) > 0)
                .sort((a, b) => getPlaycount(b) - getPlaycount(a))
        }

        if (sortByPlaytime) {
            const getGametime = (game) => {
                if (game.gametime == null) return 0
                if (typeof game.gametime === 'number') return game.gametime
                const parsed = parseInt(game.gametime, 10)
                return isNaN(parsed) ? 0 : parsed
            }

            filtered = filtered
                .filter(game => getGametime(game) > 0)
                .sort((a, b) => getGametime(b) - getGametime(a))
        }

        if (selectedLetter !== null) {
            filtered = filtered.filter(game => {
                const firstChar = game.name?.charAt(0).toUpperCase() || ''
                if (selectedLetter === '#') {
                    return !firstChar.match(/[A-Z]/)
                } else {
                    return firstChar === selectedLetter
                }
            })
        }

        if (showFavoritesOnly) {
            filtered = filtered.filter(game => game.favorite === 'true')
        }

        if (nameFilter && nameFilter.trim()) {
            const filterLower = nameFilter.toLowerCase().trim()
            filtered = filtered.filter(game => {
                const gameName = (game.name || '').toLowerCase()
                return gameName.includes(filterLower)
            })
        }

        return filtered
    }, [allGames, selectedLetter, showFavoritesOnly, sortByPlaycount, sortByPlaytime, nameFilter])

    const formatReleaseYear = (dateStr) => {
        if (!dateStr) return ''
        if (dateStr.length >= 4) {
            const year = dateStr.substring(0, 4)
            const yearNum = parseInt(year)
            if (yearNum >= 1900 && yearNum <= 2100) {
                return year
            }
        }
        return ''
    }

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

    const sortedGamesForTable = React.useMemo(() => {
        if (viewMode !== 'table') {
            return filteredGames
        }

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
                    compareResult = 1
                } else if (dateB === 'Unknown') {
                    compareResult = -1
                } else {
                    const yearA = dateA.length >= 4 ? parseInt(dateA.substring(0, 4)) : 0
                    const yearB = dateB.length >= 4 ? parseInt(dateB.substring(0, 4)) : 0
                    if (yearA && yearB) {
                        compareResult = yearA - yearB
                    } else {
                        compareResult = dateA.localeCompare(dateB)
                    }
                }
            } else if (tableSortColumn === 'playcount') {
                compareResult = getPlaycount(a) - getPlaycount(b)
            } else if (tableSortColumn === 'gametime') {
                compareResult = getGametime(a) - getGametime(b)
            } else if (tableSortColumn === 'system') {
                const sysA = (a.system || '').toLowerCase()
                const sysB = (b.system || '').toLowerCase()
                compareResult = sysA.localeCompare(sysB)
            }

            return tableSortDirection === 'desc' ? -compareResult : compareResult
        })

        return sorted
    }, [filteredGames, viewMode, tableSortColumn, tableSortDirection])

    const handleTableSort = (column) => {
        if (tableSortColumn === column) {
            setTableSortDirection(tableSortDirection === 'asc' ? 'desc' : 'asc')
        } else {
            setTableSortColumn(column)
            setTableSortDirection('asc')
        }
    }

    const displayedGames = React.useMemo(() => {
        const gamesToDisplay = viewMode === 'table' ? sortedGamesForTable : filteredGames
        return gamesToDisplay.slice(0, displayedGamesCount)
    }, [filteredGames, sortedGamesForTable, displayedGamesCount, viewMode])

    const hasMoreGames = filteredGames.length > displayedGamesCount

    useEffect(() => {
        if (observerRef.current) {
            observerRef.current.disconnect()
        }

        if (isRestoringScrollRef.current) {
            return
        }

        observerRef.current = new IntersectionObserver(
            (entries) => {
                if (entries[0].isIntersecting && hasMoreGames && !loading && !isRestoringScrollRef.current) {
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

    const letters = React.useMemo(() => {
        return ['#', ...Array.from({ length: 26 }, (_, i) => String.fromCharCode(65 + i))]
    }, [])

    const handleDownload = async (game) => {
        try {
            const result = await addToQueue(game.id, game.system)
            if (result && result.success) {
                alert('Game added to download queue!')
            }
        } catch (error) {
            console.error('Error adding to download queue:', error)
            const requiresSelection = error.response?.headers?.['x-requires-token-selection'] === 'true' ||
                error.response?.headers?.['X-Requires-Token-Selection'] === 'true'
            if (!requiresSelection) {
                const errorMsg = error.response?.data?.detail || 'Failed to add game to download queue. Please try again.'
                alert(errorMsg)
            }
        }
    }

    const handleGameClick = (game) => {
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
                    <h1>{collectionName}</h1>
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
                                setSortByPlaytime(false)
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
                                setSortByPlaycount(false)
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
                                        showSystemName={true}
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
                                            onClick={() => handleTableSort('system')}
                                            style={{ cursor: 'pointer' }}
                                        >
                                            System {tableSortColumn === 'system' && (tableSortDirection === 'asc' ? '↑' : '↓')}
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
                                        const playcount = getPlaycount(game)
                                        const gametime = getGametime(game)
                                        return (
                                            <tr
                                                key={game.id}
                                                className="game-row"
                                                ref={(el) => {
                                                    if (el) {
                                                        gameElementsRef.current[game.id] = el
                                                    } else {
                                                        delete gameElementsRef.current[game.id]
                                                    }
                                                }}
                                            >
                                                <td className="game-image-cell" onClick={() => handleGameClick(game)}>
                                                    <div className="game-table-image">
                                                        <img
                                                            src={(game.catalog_image || game.thumbnail || game.boxart || game.image) ? getMediaUrl(game.catalog_image || game.thumbnail || game.boxart || game.image, catalogType) : '/assets/images/no-image.png'}
                                                            alt={game.name}
                                                            className="table-game-image"
                                                            loading="lazy"
                                                            onError={(e) => {
                                                                e.target.onerror = null
                                                                e.target.src = '/systems_logos/default.webp'
                                                            }}
                                                        />
                                                    </div>
                                                </td>
                                                <td className="game-name-cell" onClick={() => handleGameClick(game)}>
                                                    <div className="game-name">{game.name}</div>
                                                    <div className="game-id-text">{game.id}</div>
                                                </td>
                                                <td className="game-system-cell">{game.system}</td>
                                                <td className="game-publisher-cell">{game.publisher || 'Unknown'}</td>
                                                <td className="game-release-cell">{formatReleaseYear(game.releasedate) || 'Unknown'}</td>
                                                <td className="game-playcount-cell">
                                                    {playcount > 0 ? (
                                                        <span className="stats-badge playcount" title="Playcount">
                                                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                                                <polygon points="5 3 19 12 5 21 5 3"></polygon>
                                                            </svg>
                                                            {playcount}
                                                        </span>
                                                    ) : '-'}
                                                </td>
                                                <td className="game-gametime-cell">
                                                    {gametime > 0 ? (
                                                        <span className="stats-badge gametime" title="Playtime">
                                                            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                                                <circle cx="12" cy="12" r="10"></circle>
                                                                <polyline points="12 6 12 12 16 14"></polyline>
                                                            </svg>
                                                            {formatGametime(gametime)}
                                                        </span>
                                                    ) : '-'}
                                                </td>
                                                <td className="game-actions-cell">
                                                    <button
                                                        className="download-btn"
                                                        onClick={(e) => {
                                                            e.stopPropagation()
                                                            handleDownload(game)
                                                        }}
                                                        disabled={!game.download_enabled || (!isDownload && !isFastDownload)}
                                                        title={!game.download_enabled ? "Downloads disabled" : "Download to Batocera"}
                                                    >
                                                        Download
                                                    </button>
                                                </td>
                                            </tr>
                                        )
                                    })}
                                </tbody>
                            </table>
                        </div>
                    )}

                    {hasMoreGames && (
                        <div ref={loadingRef} className="loading-more">
                            Loading more games...
                        </div>
                    )}
                </>
            )}
        </div>
    )
}

export default CollectionGames
