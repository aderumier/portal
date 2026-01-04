import React from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import SystemGames from '../components/Catalog/SystemGames'
import { useState, useEffect } from 'react'
import client from '../api/client'

const System = () => {
  const { id } = useParams()
  const [searchParams] = useSearchParams()
  const searchQuery = searchParams.get('search') || ''
  const [system, setSystem] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    loadSystem()
  }, [id])

  const loadSystem = async () => {
    try {
      setLoading(true)
      const response = await client.get('/api/systems')
      const systems = response.data.systems || []
      const foundSystem = systems.find(s => s.id === id)
      setSystem(foundSystem)
    } catch (err) {
      console.error('Error loading system:', err)
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return <div style={{ textAlign: 'center', padding: '3rem' }}>Loading...</div>
  }

  if (!system) {
    return <div style={{ textAlign: 'center', padding: '3rem' }}>System not found</div>
  }

  return <SystemGames systemId={id} systemName={system.name} searchQuery={searchQuery} />
}

export default System


