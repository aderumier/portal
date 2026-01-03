import React, { useState, useEffect, useRef, useCallback } from 'react'
import GameCard from '../components/Catalog/GameCard'
import client from '../api/client'
import './Search.css'

const Search = () => {
  const [query, setQuery] = useState('')
  const [games, setGames] = useState([])
  const [loading, setLoading] = useState(false)
  const [hasMore, setHasMore] = useState(false)
  const [page, setPage] = useState(1)
  const observerRef = useRef(null)
  const loadingRef = useRef(null)

  const searchGames = useCallback(async (searchQuery, pageNum, append = false) => {
    if (!searchQuery.trim()) {
      setGames([])
      setHasMore(false)
      return
    }

    try {
      setLoading(true)
      // Use the indexed search endpoint
      const response = await client.get('/api/search', {
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

  useEffect(() => {
    const timeoutId = setTimeout(() => {
      setPage(1)
      searchGames(query, 1, false)
    }, 500)

    return () => clearTimeout(timeoutId)
  }, [query, searchGames])

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
      await client.post('/api/download/queue', { game_id: gameId })
      alert('Game added to download queue!')
    } catch (error) {
      console.error('Error adding to download queue:', error)
      alert('Failed to add game to download queue. Please try again.')
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
          onChange={(e) => setQuery(e.target.value)}
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
    </div>
  )
}

export default Search

