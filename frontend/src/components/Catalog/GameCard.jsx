import React from 'react'
import './GameCard.css'

const GameCard = ({ game, onDownload }) => {
  const imageUrl = game.image 
    ? `/media/${game.image}` 
    : '/assets/images/no-image.png'

  return (
    <div className="game-card">
      <div className="game-card-image">
        <img src={imageUrl} alt={game.name} loading="lazy" />
      </div>
      <div className="game-card-content">
        <h3 className="game-card-title">{game.name}</h3>
        {game.description && (
          <p className="game-card-description">{game.description}</p>
        )}
        <div className="game-card-actions">
          <button 
            className="download-btn" 
            onClick={() => onDownload(game.id)}
          >
            Download
          </button>
        </div>
      </div>
    </div>
  )
}

export default GameCard

