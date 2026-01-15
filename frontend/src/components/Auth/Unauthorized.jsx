import React from 'react'
import { Link } from 'react-router-dom'

const Unauthorized = () => {
  return (
    <div style={{
      display: 'flex',
      justifyContent: 'center',
      alignItems: 'center',
      height: '100vh',
      flexDirection: 'column',
      gap: '1rem',
      textAlign: 'center',
      padding: '2rem'
    }}>
      <h1>Access Denied</h1>
      <p>You must be a member of the Team Pixel Nostalgia Discord server to access this application.</p>
      <p>Please join the server and try again.</p>
      <Link to="/" style={{ 
        padding: '0.5rem 1rem', 
        backgroundColor: '#5865F2', 
        color: 'white', 
        textDecoration: 'none',
        borderRadius: '4px'
      }}>
        Go to Home
      </Link>
    </div>
  )
}

export default Unauthorized













