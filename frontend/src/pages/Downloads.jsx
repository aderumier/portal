import React, { useState, useEffect } from 'react'
import client from '../api/client'
import './Downloads.css'

const Downloads = () => {
  const [queue, setQueue] = useState([])
  const [loading, setLoading] = useState(true)
  const [view, setView] = useState(localStorage.getItem('downloads-view') || 'grid')

  useEffect(() => {
    loadQueue()
  }, [])

  const loadQueue = async () => {
    try {
      setLoading(true)
      const response = await client.get('/api/download/queue')
      setQueue(response.data || [])
    } catch (error) {
      console.error('Error loading queue:', error)
    } finally {
      setLoading(false)
    }
  }

  const handleRemove = async (gameId) => {
    try {
      const encodedGameId = encodeURIComponent(encodeURIComponent(gameId))
      await client.delete(`/api/download/queue/${encodedGameId}`)
      await loadQueue()
    } catch (error) {
      console.error('Error removing game:', error)
      alert('Failed to remove game from queue')
    }
  }

  const handleClear = async () => {
    if (!confirm('Are you sure you want to clear your entire download queue?')) {
      return
    }

    try {
      await client.delete('/api/download/queue')
      await loadQueue()
    } catch (error) {
      console.error('Error clearing queue:', error)
      alert('Failed to clear queue')
    }
  }

  const handleViewChange = (newView) => {
    setView(newView)
    localStorage.setItem('downloads-view', newView)
  }

  if (loading) {
    return <div className="loading">Loading downloads...</div>
  }

  return (
    <div className="downloads-page">
      <div className="downloads-header">
        <h1>My Downloads</h1>
        <div className="downloads-actions">
          <div className="view-toggle">
            <button
              className={`view-btn ${view === 'grid' ? 'active' : ''}`}
              onClick={() => handleViewChange('grid')}
              title="Grid View"
            >
              Grid
            </button>
            <button
              className={`view-btn ${view === 'table' ? 'active' : ''}`}
              onClick={() => handleViewChange('table')}
              title="Table View"
            >
              Table
            </button>
          </div>
          <button className="clear-queue-btn" onClick={handleClear}>
            Clear Queue
          </button>
        </div>
      </div>

      {queue.length === 0 ? (
        <div className="no-downloads">No games in your download queue</div>
      ) : (
        <>
          {view === 'grid' && (
            <div className="downloads-grid">
              {queue.map((item) => (
                <div key={item.id} className="download-card">
                  {item.image && (
                    <div className="download-card-image">
                      <img
                        src={`/media/${item.image}`}
                        alt={item.game_name}
                        loading="lazy"
                      />
                    </div>
                  )}
                  <div className="download-card-content">
                    <h3 className="game-title">{item.game_name}</h3>
                    <div className="game-meta">
                      <span className="system-tag">{item.system_name}</span>
                      <span className={`status-tag ${item.status}`}>
                        {item.status.charAt(0).toUpperCase() + item.status.slice(1)}
                      </span>
                    </div>
                    <div className="download-actions">
                      <button
                        className="remove-download-btn"
                        onClick={() => handleRemove(item.game_id)}
                      >
                        Remove
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )}

          {view === 'table' && (
            <div className="downloads-table">
              <table>
                <thead>
                  <tr>
                    <th>Game</th>
                    <th>System</th>
                    <th>Status</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {queue.map((item) => (
                    <tr key={item.id}>
                      <td className="game-info">
                        {item.image && (
                          <img
                            className="table-thumbnail"
                            src={`/media/${item.image}`}
                            alt={item.game_name}
                            loading="lazy"
                          />
                        )}
                        <span>{item.game_name}</span>
                      </td>
                      <td>{item.system_name}</td>
                      <td>
                        <span className={`status-tag ${item.status}`}>
                          {item.status.charAt(0).toUpperCase() + item.status.slice(1)}
                        </span>
                      </td>
                      <td>
                        <button
                          className="remove-download-btn"
                          onClick={() => handleRemove(item.game_id)}
                        >
                          Remove
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  )
}

export default Downloads

