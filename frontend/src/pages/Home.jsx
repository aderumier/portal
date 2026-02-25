import React from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import WarningModal from '../components/WarningModal/WarningModal'
import client from '../api/client'
import './Home.css'

const Home = () => {
  const { isAuthenticated } = useAuth()
  const [outdatedDevices, setOutdatedDevices] = React.useState([])
  const [showWarningModal, setShowWarningModal] = React.useState(false)
  const [minClientVersion, setMinClientVersion] = React.useState(null)

  React.useEffect(() => {
    if (isAuthenticated) {
      const fetchDevices = async () => {
        try {
          const response = await client.get('/api/users/me/devices')
          if (response.data && response.data.outdated_devices && response.data.outdated_devices.length > 0) {
            setOutdatedDevices(response.data.outdated_devices)
            setMinClientVersion(response.data.min_client_version)
            setShowWarningModal(true)
          }
        } catch (error) {
          console.error("Error fetching devices:", error)
        }
      }
      fetchDevices()
    }
  }, [isAuthenticated])

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

      <WarningModal
        isOpen={showWarningModal}
        onClose={() => setShowWarningModal(false)}
        title="Outdated Clients Detected"
        message={`Some of your connected clients are using an outdated version. Please update them to at least version ${minClientVersion} to continue adding downloads.`}
        devices={outdatedDevices}
      />
    </>
  )
}

export default Home

