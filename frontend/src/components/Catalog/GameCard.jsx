import React from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../../context/AuthContext'
import { getMediaUrl } from '../../utils/constants'
import './GameCard.css'

const GameCard = ({ game, onDownload, onGameClick }) => {
  const navigate = useNavigate()
  const { isDownload, isFastDownload } = useAuth()
  
  // Backend now returns the selected image in the 'image' field (priority: thumbnail > boxart > extra1 > image)
  const imageUrl = game.image ? getMediaUrl(game.image) : '/assets/images/no-image.png'

  const handleCardClick = (e) => {
    // Don't navigate if clicking the download button
    if (e.target.closest('.download-btn')) {
      return
    }
    
    // If onGameClick is provided, use it (for saving game ID)
    if (onGameClick) {
      onGameClick(game)
      return
    }
    
    // Navigate to game details page
    // game.id is the path from gamelist.xml (e.g., "./game.zip" or "system/game.zip")
    // We need just the filename/path part without the system prefix
    let gameId = game.id.replace(/^\.\//, '')
    // Remove system prefix if present
    if (gameId.startsWith(`${game.system}/`)) {
      gameId = gameId.substring(game.system.length + 1)
    }
    navigate(`/game/${game.system}/${encodeURIComponent(gameId)}`)
  }

  const handleDownloadClick = (e) => {
    e.stopPropagation()
    onDownload(game.id)
  }

  return (
    <div 
      className="game-card" 
      onClick={handleCardClick}
    >
      <div className="game-card-image">
        <img src={imageUrl} alt={game.name} loading="lazy" />
      </div>
      <div className="game-card-content">
        <h3 className="game-card-title">{game.name}</h3>
        {(isDownload || isFastDownload) && game?.download_enabled !== false && (
          <div className="game-card-actions">
            <button 
              className="download-btn" 
              onClick={handleDownloadClick}
            >
              Download
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

export default GameCard

