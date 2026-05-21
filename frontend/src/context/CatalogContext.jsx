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
  const [canViewReleases, setCanViewReleases] = useState(true)
  const [canViewWip, setCanViewWip] = useState(true)
  const [canContribute, setCanContribute] = useState(false)
  const [loading, setLoading] = useState(true)

  // Load preference from API on mount
  useEffect(() => {
    const loadPreference = async () => {
      try {
        const response = await client.get('/api/catalog/preference')
        const viewReleases = response.data.can_view_releases !== false
        const viewWip = response.data.can_view_wip !== false
        setCanViewReleases(viewReleases)
        setCanViewWip(viewWip)
        setCanContribute(response.data.can_contribute === true)
        setCatalogTypeState(response.data.catalog_type || 'releases')
      } catch (error) {
        console.error('Error loading catalog preference:', error)
        setCatalogTypeState('releases')
        setCanViewReleases(true)
        setCanViewWip(true)
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
    canViewReleases,
    canViewWip,
    canContribute,
    // Legacy alias kept for any remaining consumers
    releasesEnabled: canViewReleases,
    loading
  }

  return (
    <CatalogContext.Provider value={value}>
      {children}
    </CatalogContext.Provider>
  )
}
