import React, { useState, useEffect } from 'react'
import SystemsList from '../components/Catalog/SystemsList'
import client from '../api/client'

const Systems = () => {
  const [systems, setSystems] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    loadSystems()
  }, [])

  const loadSystems = async () => {
    try {
      setLoading(true)
      const response = await client.get('/api/systems')
      setSystems(response.data.systems || [])
    } catch (err) {
      console.error('Error loading systems:', err)
      setError('Failed to load systems')
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return <div style={{ textAlign: 'center', padding: '3rem' }}>Loading systems...</div>
  }

  if (error) {
    return <div style={{ textAlign: 'center', padding: '3rem', color: 'red' }}>{error}</div>
  }

  return <SystemsList systems={systems} />
}

export default Systems

