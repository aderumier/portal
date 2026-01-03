import React, { useState, useEffect, useRef, useCallback } from 'react'
import GameCard from './GameCard'
import client from '../../api/client'
import './SystemGames.css'

const SystemGames = ({ systemId, systemName, searchQuery = '' }) => {
  const [games, setGames] = useState([])
  const [loading, setLoading] = useState(true)
  const [hasMore, setHasMore] = useState(true)
  const [page, setPage] = useState(1)
  const [error, setError] = useState(null)
  const observerRef = useRef(null)
  const loadingRef = useRef(null)

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
      
      const response = await client.get(`/api/games/${systemId}`, { params })
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
      await client.post('/api/download/queue', { game_id: gameId })
      alert('Game added to download queue!')
    } catch (error) {
      console.error('Error adding to download queue:', error)
      alert('Failed to add game to download queue. Please try again.')
    }
  }

  if (loading && games.length === 0) {
    return <div className="loading">Loading games...</div>
  }

  if (error && games.length === 0) {
    return <div className="error">{error}</div>
  }

  return (
    <div className="system-games">
      <h1>{systemName}</h1>
      {searchQuery && <p>Search results for: "{searchQuery}"</p>}
      
      {games.length === 0 ? (
        <div className="no-games">No games found</div>
      ) : (
        <>
          <div className="games-grid">
            {games.map((game) => (
              <GameCard 
                key={game.id} 
                game={game} 
                onDownload={handleDownload}
              />
            ))}
          </div>
          
          {hasMore && (
            <div ref={loadingRef} className="load-more-trigger">
              {loading && <p>Loading more games...</p>}
            </div>
          )}
        </>
      )}
    </div>
  )
}

export default SystemGames

