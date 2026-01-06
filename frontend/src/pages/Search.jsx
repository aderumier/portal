import React, { useState, useEffect, useRef, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import GameCard from '../components/Catalog/GameCard'
import TokenSelectorDropdown from '../components/TokenSelector/TokenSelectorDropdown'
import { useDownloadWithToken } from '../hooks/useDownloadWithToken'
import client from '../api/client'
import './Search.css'

const Search = () => {
  const [searchParams, setSearchParams] = useSearchParams()
  const urlQuery = searchParams.get('q') || ''
  const [query, setQuery] = useState(urlQuery)
  const [games, setGames] = useState([])
  const [loading, setLoading] = useState(false)
  const [hasMore, setHasMore] = useState(false)
  const [page, setPage] = useState(1)
  const observerRef = useRef(null)
  const loadingRef = useRef(null)
  const { addToQueue, handleTokenSelected, cancelTokenSelection, showTokenSelector } = useDownloadWithToken()
  const hasSearchedRef = useRef(false)

  const searchGames = useCallback(async (searchQuery, pageNum, append = false) => {
    if (!searchQuery.trim()) {
      setGames([])
      setHasMore(false)
      return
    }

    try {
      setLoading(true)
      // Use the indexed search endpoint
      const response = await client.get('/api/catalog/search', {
        params: {
          q: searchQuery,
          page: pageNum,
          limit: 12
        }
      })
      
      const newGames = response.data.results || []
      
      if (append) {
        setGames(prev => [...prev, ...newGames])
      } else {
        setGames(newGames)
      }
      
      setHasMore(response.data.hasMore || false)
    } catch (error) {
      console.error('Error searching games:', error)
    } finally {
      setLoading(false)
    }
  }, [])

  // Update query when URL parameter changes
  useEffect(() => {
    const urlQuery = searchParams.get('q') || ''
    if (urlQuery !== query) {
      setQuery(urlQuery)
      setPage(1)
    }
  }, [searchParams, query])

  // Trigger search when query changes
  useEffect(() => {
    const currentQuery = query.trim()
    if (!currentQuery) {
      setGames([])
      setHasMore(false)
      hasSearchedRef.current = false
      return
    }

    // Trigger search with a small debounce
    const timeoutId = setTimeout(() => {
      searchGames(currentQuery, 1, false)
      hasSearchedRef.current = true
    }, 300)

    return () => clearTimeout(timeoutId)
  }, [query, searchGames])

  // Trigger initial search on mount if URL has query parameter
  useEffect(() => {
    const initialQuery = searchParams.get('q') || ''
    if (initialQuery.trim() && !hasSearchedRef.current) {
      // Small delay to ensure state is initialized
      const timeoutId = setTimeout(() => {
        searchGames(initialQuery, 1, false)
        hasSearchedRef.current = true
      }, 100)
      return () => clearTimeout(timeoutId)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []) // Only run on mount

  const handleQueryChange = (e) => {
    const newQuery = e.target.value
    setQuery(newQuery)
    // Update URL parameter
    if (newQuery.trim()) {
      setSearchParams({ q: newQuery })
    } else {
      setSearchParams({})
    }
  }

  useEffect(() => {
    if (observerRef.current) {
      observerRef.current.disconnect()
    }

    observerRef.current = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && hasMore && !loading && query.trim()) {
          const nextPage = page + 1
          setPage(nextPage)
          searchGames(query, nextPage, true)
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
  }, [hasMore, loading, page, query, searchGames])

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

  return (
    <div className="search-page">
      <h1>Search Games</h1>
      <div className="search-input-container">
        <input
          type="text"
          className="search-input"
          placeholder="Search for games..."
          value={query}
          onChange={handleQueryChange}
        />
      </div>

      {loading && games.length === 0 && (
        <div className="loading">Searching...</div>
      )}

      {games.length > 0 && (
        <>
          <div className="games-grid">
            {games.map((game) => (
              <GameCard 
                key={`${game.system}-${game.id}`} 
                game={game} 
                onDownload={handleDownload}
              />
            ))}
          </div>
          
          {hasMore && (
            <div ref={loadingRef} className="load-more-trigger">
              {loading && <p>Loading more results...</p>}
            </div>
          )}
        </>
      )}

      {!loading && query.trim() && games.length === 0 && (
        <div className="no-results">No games found</div>
      )}
      <TokenSelectorDropdown
        isOpen={showTokenSelector}
        onClose={cancelTokenSelection}
        onSelect={handleTokenSelected}
      />
    </div>
  )
}

export default Search

