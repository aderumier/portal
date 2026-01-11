import React, { createContext, useContext, useState, useEffect } from 'react'
import client from '../api/client'

const CatalogContext = createContext(null)

export const useCatalog = () => {
  const context = useContext(CatalogContext)
  if (!context) {
    throw new Error('useCatalog must be used within CatalogProvider')
  }
  return context
}

export const CatalogProvider = ({ children }) => {
  const [catalogType, setCatalogTypeState] = useState('releases')
  const [releasesEnabled, setReleasesEnabled] = useState(true)
  const [loading, setLoading] = useState(true)

  // Load preference from API on mount
  useEffect(() => {
    const loadPreference = async () => {
      try {
        const response = await client.get('/api/catalog/preference')
        const enabled = response.data.releases_enabled !== false // Default to true if not present
        setReleasesEnabled(enabled)
        const preference = response.data.catalog_type || 'releases'
        // If Releases is disabled and preference is 'releases', default to 'wip'
        const defaultType = (enabled ? preference : (preference === 'releases' ? 'wip' : preference))
        setCatalogTypeState(defaultType)
      } catch (error) {
        console.error('Error loading catalog preference:', error)
        // Default to 'releases' on error (assuming it's enabled)
        setCatalogTypeState('releases')
        setReleasesEnabled(true)
      } finally {
        setLoading(false)
      }
    }
    loadPreference()
  }, [])

  // Set catalog type and update API preference
  const setCatalogType = async (type) => {
    if (type !== 'wip' && type !== 'releases') {
      console.error('Invalid catalog type:', type)
      return
    }
    
    try {
      await client.put('/api/catalog/preference', null, {
        params: { catalog_type: type }
      })
      setCatalogTypeState(type)
    } catch (error) {
      console.error('Error setting catalog preference:', error)
      // Still update state locally even if API call fails
      setCatalogTypeState(type)
    }
  }

  const value = {
    catalogType,
    setCatalogType,
    releasesEnabled,
    loading
  }

  return (
    <CatalogContext.Provider value={value}>
      {children}
    </CatalogContext.Provider>
  )
}
