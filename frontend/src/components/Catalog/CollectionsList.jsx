import React, { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { useCatalog } from '../../context/CatalogContext'
import './CollectionsList.css'

const CollectionsList = ({ collections }) => {
    const { catalogType } = useCatalog()
    const [viewMode, setViewMode] = useState('grid') // 'grid' or 'table'
    const [sortColumn, setSortColumn] = useState('name') // 'name', 'games'
    const [sortDirection, setSortDirection] = useState('asc') // 'asc' or 'desc'

    // Load view preference from localStorage
    useEffect(() => {
        const savedView = localStorage.getItem('collectionsViewMode')
        if (savedView === 'table' || savedView === 'grid') {
            setViewMode(savedView)
        }
    }, [])

    // Save view preference to localStorage
    const handleViewChange = (mode) => {
        setViewMode(mode)
        localStorage.setItem('collectionsViewMode', mode)
    }

    const sortedCollections = [...collections].sort((a, b) => {
        let compareResult = 0
        if (sortColumn === 'name') {
            compareResult = (a.name || '').localeCompare(b.name || '')
        } else if (sortColumn === 'games') {
            compareResult = (a.gameCount || 0) - (b.gameCount || 0)
        }
        return sortDirection === 'desc' ? -compareResult : compareResult
    })

    // handleSort must be defined before using it in JSX
    const handleSort = React.useCallback((column) => {
        setSortColumn(prevColumn => {
            if (prevColumn === column) {
                // Toggle direction if clicking the same column
                setSortDirection(prevDir => prevDir === 'asc' ? 'desc' : 'asc')
                return column
            } else {
                // New column, default to ascending
                setSortDirection('asc')
                return column
            }
        })
    }, [])

    const getCollectionImagePath = (collectionId) => {
        // Remove 'custom-' prefix from the image filename if it exists
        const imageName = collectionId.replace(/^custom-/, '')
        return `/collection_logos/${imageName}.png`
    }

    return (
        <div className="systems-list">
            <div className="systems-header">
                <h1>Collections</h1>
                <div className="view-toggle">
                    <button
                        className={`view-toggle-btn ${viewMode === 'grid' ? 'active' : ''}`}
                        onClick={() => handleViewChange('grid')}
                        title="Grid View"
                        aria-label="Grid View"
                    >
                        <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
                            <rect x="2" y="2" width="6" height="6" rx="1" stroke="currentColor" strokeWidth="1.5" fill="none" />
                            <rect x="12" y="2" width="6" height="6" rx="1" stroke="currentColor" strokeWidth="1.5" fill="none" />
                            <rect x="2" y="12" width="6" height="6" rx="1" stroke="currentColor" strokeWidth="1.5" fill="none" />
                            <rect x="12" y="12" width="6" height="6" rx="1" stroke="currentColor" strokeWidth="1.5" fill="none" />
                        </svg>
                    </button>
                    <button
                        className={`view-toggle-btn ${viewMode === 'table' ? 'active' : ''}`}
                        onClick={() => handleViewChange('table')}
                        title="Table View"
                        aria-label="Table View"
                    >
                        <svg width="20" height="20" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg">
                            <path d="M2 4H18M2 8H18M2 12H18M2 16H18" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                            <path d="M2 4V16M6 4V16M10 4V16M14 4V16M18 4V16" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                        </svg>
                    </button>
                </div>
            </div>

            {viewMode === 'grid' ? (
                <div className="systems-by-hardware">
                    <div className="hardware-category">
                        <div className="systems-grid">
                            {sortedCollections.map((collection) => {
                                const collectionImage = getCollectionImagePath(collection.id)
                                return (
                                    <Link
                                        key={collection.id}
                                        to={`/collection/${collection.id}`}
                                        className="system-card"
                                    >
                                        <div className="system-card-image">
                                            <img
                                                src={collectionImage}
                                                alt={collection.name}
                                                onError={(e) => {
                                                    // Fallback to a placeholder if image doesn't exist
                                                    e.target.style.display = 'none'
                                                }}
                                            />
                                        </div>
                                        <div className="system-card-content">
                                            <h2>{collection.name}</h2>
                                            <p>{collection.gameCount} games</p>
                                        </div>
                                    </Link>
                                )
                            })}
                        </div>
                    </div>
                </div>
            ) : (
                <div className="systems-by-hardware">
                    <div className="hardware-category">
                        <div className="systems-table-container">
                            <table className="systems-table">
                                <thead>
                                    <tr>
                                        <th>Image</th>
                                        <th
                                            className="sortable"
                                            onClick={() => handleSort('name')}
                                            style={{ cursor: 'pointer' }}
                                        >
                                            Collection Name {sortColumn === 'name' && (sortDirection === 'asc' ? '↑' : '↓')}
                                        </th>
                                        <th
                                            className="sortable"
                                            onClick={() => handleSort('games')}
                                            style={{ cursor: 'pointer' }}
                                        >
                                            Games {sortColumn === 'games' && (sortDirection === 'asc' ? '↑' : '↓')}
                                        </th>
                                        <th>Actions</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {sortedCollections.map((collection) => {
                                        const collectionImage = getCollectionImagePath(collection.id)
                                        return (
                                            <tr key={collection.id}>
                                                <td className="system-image-cell">
                                                    <img
                                                        src={collectionImage}
                                                        alt={collection.name}
                                                        className="system-table-image"
                                                        onError={(e) => {
                                                            // Hide image if it doesn't exist
                                                            e.target.style.display = 'none'
                                                        }}
                                                    />
                                                </td>
                                                <td className="system-name-cell">
                                                    <Link to={`/collection/${collection.id}`} className="system-link">
                                                        {collection.name}
                                                    </Link>
                                                </td>
                                                <td className="system-games-cell">
                                                    <span className="games-count">{collection.gameCount} games</span>
                                                </td>
                                                <td className="system-actions-cell">
                                                    <Link
                                                        to={`/collection/${collection.id}`}
                                                        className="view-system-btn"
                                                    >
                                                        View Games
                                                    </Link>
                                                </td>
                                            </tr>
                                        )
                                    })}
                                </tbody>
                            </table>
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}

export default CollectionsList
