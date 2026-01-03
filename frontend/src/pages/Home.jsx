import React from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

const Home = () => {
  const { isAuthenticated } = useAuth()

  return (
    <div style={{ 
      textAlign: 'center', 
      padding: '3rem 1rem',
      maxWidth: '800px',
      margin: '0 auto'
    }}>
      <h1>Welcome to Batocera Games Catalog</h1>
      <p style={{ fontSize: '1.2rem', marginBottom: '2rem', color: '#666' }}>
        Browse and download games from your Batocera system
      </p>
      
      {!isAuthenticated ? (
        <div>
          <Link 
            to="/login" 
            style={{
              display: 'inline-block',
              padding: '1rem 2rem',
              backgroundColor: '#5865F2',
              color: 'white',
              textDecoration: 'none',
              borderRadius: '8px',
              fontSize: '1.1rem'
            }}
          >
            Login with Discord
          </Link>
        </div>
      ) : (
        <div>
          <Link 
            to="/systems" 
            style={{
              display: 'inline-block',
              padding: '1rem 2rem',
              backgroundColor: '#5865F2',
              color: 'white',
              textDecoration: 'none',
              borderRadius: '8px',
              fontSize: '1.1rem',
              marginRight: '1rem'
            }}
          >
            Browse Systems
          </Link>
          <Link 
            to="/search" 
            style={{
              display: 'inline-block',
              padding: '1rem 2rem',
              backgroundColor: '#5865F2',
              color: 'white',
              textDecoration: 'none',
              borderRadius: '8px',
              fontSize: '1.1rem'
            }}
          >
            Search Games
          </Link>
        </div>
      )}
    </div>
  )
}

export default Home

