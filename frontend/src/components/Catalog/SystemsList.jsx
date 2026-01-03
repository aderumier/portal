import React from 'react'
import { Link } from 'react-router-dom'
import './SystemsList.css'

const SystemsList = ({ systems }) => {
  return (
    <div className="systems-list">
      <h1>Game Systems</h1>
      <div className="systems-grid">
        {systems.map((system) => (
          <Link 
            key={system.id} 
            to={`/system/${system.id}`}
            className="system-card"
          >
            <div className="system-card-content">
              <h2>{system.name}</h2>
              <p>{system.gameCount} games</p>
            </div>
          </Link>
        ))}
      </div>
    </div>
  )
}

export default SystemsList

