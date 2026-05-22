import React, { useState, useEffect } from 'react'
import SystemsList from '../components/Catalog/SystemsList'
import { useCatalog } from '../context/CatalogContext'
import { getSystems } from '../api/catalog'

const Systems = ({ catalogType: propCatalogType }) => {
  const { catalogType: contextCatalogType, setCatalogType } = useCatalog()
  const catalogType = propCatalogType || contextCatalogType

  const [systems, setSystems] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  // Sync context so that SystemGames (reached via /system/:id) uses the right catalog
  useEffect(() => {
    if (propCatalogType && propCatalogType !== contextCatalogType) {
      setCatalogType(propCatalogType)
    }
  }, [propCatalogType]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const loadSystems = async () => {
      try {
        setLoading(true)
        const response = await getSystems(catalogType)
        setSystems(response.systems || [])
      } catch (err) {
        console.error('Error loading systems:', err)
        setError('Failed to load systems')
      } finally {
        setLoading(false)
      }
    }
    loadSystems()
  }, [catalogType])

  if (loading) {
    return <div style={{ textAlign: 'center', padding: '3rem' }}>Loading systems...</div>
  }

  if (error) {
    return <div style={{ textAlign: 'center', padding: '3rem', color: 'red' }}>{error}</div>
  }

  return <SystemsList systems={systems} />
}

export default Systems


