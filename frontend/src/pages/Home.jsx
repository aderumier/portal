import React from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import './Home.css'

const Home = () => {
  const { isAuthenticated } = useAuth()

  return (
    <>
      <div className="hero">
        <div className="hero-content">
          <h1>Welcome to Pixel Nostalgia</h1>
          <div className="hero-image">
            <img 
              src="https://pixelnostalgia.github.io/media/posts/4/responsive/background-xl.webp" 
              alt="Pixel Nostalgia Background" 
              loading="lazy"
            />
          </div>
          <p>Your retro game library for Team Pixel Nostalgia members</p>
          {!isAuthenticated ? (
            <Link to="/login" className="hero-cta">Login with Discord</Link>
          ) : (
            <Link to="/systems" className="hero-cta">Browse Games</Link>
          )}
        </div>
      </div>

      <div className="home-features">
        <div className="feature">
          <i className="fas fa-gamepad"></i>
          <h2>Extensive Collection</h2>
          <p>Browse through our curated collection of retro games across multiple systems</p>
        </div>
        <div className="feature">
          <i className="fas fa-download"></i>
          <h2>Download Access</h2>
          <p>Creators can download games directly through our secure download system</p>
        </div>
        <div className="feature">
          <i className="fas fa-search"></i>
          <h2>Advanced Search</h2>
          <p>Find your favorite games quickly with our powerful search functionality</p>
        </div>
      </div>
    </>
  )
}

export default Home

