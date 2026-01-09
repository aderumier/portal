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
  const [loading, setLoading] = useState(true)

  // Load preference from API on mount
  useEffect(() => {
    const loadPreference = async () => {
      try {
        const response = await client.get('/api/catalog/preference')
        setCatalogTypeState(response.data.catalog_type || 'releases')
      } catch (error) {
        console.error('Error loading catalog preference:', error)
        // Default to 'releases' on error
        setCatalogTypeState('releases')
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
    loading
  }

  return (
    <CatalogContext.Provider value={value}>
      {children}
    </CatalogContext.Provider>
  )
}
