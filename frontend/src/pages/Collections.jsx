import React, { useState, useEffect } from 'react'
import CollectionsList from '../components/Catalog/CollectionsList'
import { useCatalog } from '../context/CatalogContext'
import { getCollections } from '../api/collections'

const Collections = () => {
    const { catalogType } = useCatalog()
    const [collections, setCollections] = useState([])
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState(null)

    useEffect(() => {
        loadCollections()
    }, [catalogType])

    const loadCollections = async () => {
        try {
            setLoading(true)
            const response = await getCollections(catalogType)
            setCollections(response.collections || [])
        } catch (err) {
            console.error('Error loading collections:', err)
            setError('Failed to load collections')
        } finally {
            setLoading(false)
        }
    }

    if (loading) {
        return <div style={{ textAlign: 'center', padding: '3rem' }}>Loading collections...</div>
    }

    if (error) {
        return <div style={{ textAlign: 'center', padding: '3rem', color: 'red' }}>{error}</div>
    }

    return <CollectionsList collections={collections} />
}

export default Collections
