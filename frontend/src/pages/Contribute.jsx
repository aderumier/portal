import React, { useState, useEffect } from 'react'
import ContributeSystemsList from '../components/Catalog/ContributeSystemsList'
import { getContributeSystems } from '../api/catalog'

const Contribute = () => {
  const [systems, setSystems] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    loadSystems()
  }, [])

  const loadSystems = async () => {
    try {
      setLoading(true)
      const response = await getContributeSystems()
      setSystems(response.systems || [])
    } catch (err) {
      console.error('Error loading contribute systems:', err)
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

  return <ContributeSystemsList systems={systems} />
}

export default Contribute
