import React, { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'
import client from '../../api/client'
import './HeaderSearch.css'

const HeaderSearch = () => {
  const { isAuthenticated } = useAuth()
  const [query, setQuery] = useState('')
  const [results, setResults] = useState([])
  const [loading, setLoading] = useState(false)
  const [showResults, setShowResults] = useState(false)
  const [selectedIndex, setSelectedIndex] = useState(-1)
  const navigate = useNavigate()
  const searchRef = useRef(null)
  const resultsRef = useRef(null)

  // Don't render if not authenticated
  if (!isAuthenticated) {
    return null
  }

  useEffect(() => {
    const handleClickOutside = (event) => {
      if (searchRef.current && !searchRef.current.contains(event.target)) {
        setShowResults(false)
      }
    }

    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  useEffect(() => {
    if (!query.trim()) {
      setResults([])
      setShowResults(false)
      return
    }

    const timeoutId = setTimeout(() => {
      performSearch(query)
    }, 300) // Debounce search

    return () => clearTimeout(timeoutId)
  }, [query])

  const performSearch = async (searchQuery) => {
    try {
      setLoading(true)
      const response = await client.get('/api/search/quick', {
        params: {
          q: searchQuery,
          limit: 10
        }
      })
      setResults(response.data.results || [])
      setShowResults(true)
      setSelectedIndex(-1)
    } catch (error) {
      console.error('Search error:', error)
      setResults([])
    } finally {
      setLoading(false)
    }
  }

  const handleInputChange = (e) => {
    setQuery(e.target.value)
  }

  const handleKeyDown = (e) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setSelectedIndex(prev => 
        prev < results.length - 1 ? prev + 1 : prev
      )
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setSelectedIndex(prev => prev > 0 ? prev - 1 : -1)
    } else if (e.key === 'Enter' && selectedIndex >= 0 && results[selectedIndex]) {
      e.preventDefault()
      handleGameClick(results[selectedIndex])
    } else if (e.key === 'Escape') {
      setShowResults(false)
      setQuery('')
    }
  }

  const handleGameClick = (game) => {
    setShowResults(false)
    setQuery('')
    navigate(`/system/${game.system}`, { state: { highlightGame: game.id } })
  }

  const handleInputFocus = () => {
    if (results.length > 0) {
      setShowResults(true)
    }
  }

  return (
    <div className="header-search" ref={searchRef}>
      <div className="search-input-wrapper">
        <input
          type="text"
          className="search-input"
          placeholder="Search games..."
          value={query}
          onChange={handleInputChange}
          onKeyDown={handleKeyDown}
          onFocus={handleInputFocus}
        />
        {loading && <span className="search-loading">⏳</span>}
        {query && !loading && (
          <button
            className="search-clear"
            onClick={() => {
              setQuery('')
              setResults([])
              setShowResults(false)
            }}
          >
            ×
          </button>
        )}
      </div>
      
      {showResults && results.length > 0 && (
        <div className="search-results" ref={resultsRef}>
          {results.map((game, index) => (
            <div
              key={`${game.system}-${game.id}`}
              className={`search-result-item ${index === selectedIndex ? 'selected' : ''}`}
              onClick={() => handleGameClick(game)}
              onMouseEnter={() => setSelectedIndex(index)}
            >
              {game.image && (
                <img
                  src={`/media/${game.image}`}
                  alt={game.name}
                  className="search-result-image"
                />
              )}
              <div className="search-result-content">
                <div className="search-result-name">{game.name}</div>
                <div className="search-result-meta">
                  <span className="search-result-system">{game.systemName}</span>
                </div>
              </div>
            </div>
          ))}
          {results.length >= 10 && (
            <div 
              className="search-result-more"
              onClick={() => {
                setShowResults(false)
                navigate(`/search?q=${encodeURIComponent(query)}`)
              }}
            >
              View all results for "{query}"
            </div>
          )}
        </div>
      )}
      
      {showResults && !loading && query && results.length === 0 && (
        <div className="search-results">
          <div className="search-no-results">No games found</div>
        </div>
      )}
    </div>
  )
}

export default HeaderSearch

