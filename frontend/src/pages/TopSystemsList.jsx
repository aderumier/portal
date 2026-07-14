import React, { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { getTopSystems } from '../api/catalog'
import { useCatalog } from '../context/CatalogContext'
import '../components/Catalog/TopGamesList.css'

const TopSystemsList = () => {
    const { catalogType } = useCatalog()
    const [systems, setSystems] = useState([])
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState(null)
    const [sortColumn, setSortColumn] = useState('download_count')
    const [sortDirection, setSortDirection] = useState('desc')
    const navigate = useNavigate()

    useEffect(() => {
        loadTopSystems()
    }, [catalogType])

    const loadTopSystems = async () => {
        try {
            setLoading(true)
            const data = await getTopSystems(100, catalogType, 'download_count')
            setSystems(data)
        } catch (err) {
            console.error('Error loading top systems:', err)
            setError('Failed to load top systems')
        } finally {
            setLoading(false)
        }
    }

    const handleSort = (column) => {
        if (sortColumn === column) {
            setSortDirection(dir => dir === 'asc' ? 'desc' : 'asc')
        } else {
            setSortColumn(column)
            setSortDirection(column === 'name' ? 'asc' : 'desc')
        }
    }

    const formatBytes = (bytes) => {
        if (!bytes) return '0 B'
        if (bytes < 1024) return `${bytes} B`
        if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(2)} KB`
        if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(2)} MB`
        return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`
    }

    const sortedSystems = [...systems].sort((a, b) => {
        let cmp
        if (sortColumn === 'name') {
            cmp = (a.name || '').localeCompare(b.name || '')
        } else {
            cmp = (a[sortColumn] || 0) - (b[sortColumn] || 0)
        }
        return sortDirection === 'desc' ? -cmp : cmp
    })

    const handleSystemClick = (systemId) => {
        navigate(`/systems/${systemId}`) // Assuming this is the route for system details or game list for system
    }

    const SortHeader = ({ column, label, className }) => (
        <th className={`sortable${className ? ` ${className}` : ''}`} onClick={() => handleSort(column)}>
            {label} {sortColumn === column && (sortDirection === 'asc' ? '↑' : '↓')}
        </th>
    )

    if (loading) return <div className="loading">Loading top systems...</div>
    if (error) return <div className="error">{error}</div>

    return (
        <div className="top-games-page">
            <h1>Top Systems Downloads</h1>

            <div className="games-table-container">
                <table className="games-table">
                    <thead>
                        <tr>
                            <th className="rank-col">#</th>
                            <SortHeader column="name" label="System Name" />
                            <SortHeader column="gameCount" label="Game Count" />
                            <SortHeader column="download_count" label="Total Downloads" />
                            <SortHeader column="download_size" label="Total Size" />
                        </tr>
                    </thead>
                    <tbody>
                        {sortedSystems.map((system, index) => (
                            <tr key={system.id} onClick={() => handleSystemClick(system.id)} className="game-row">
                                <td className="rank-col">{index + 1}</td>
                                <td className="game-name-cell">{system.name}</td>
                                <td>{system.gameCount}</td>
                                <td className="stat-cell">{system.download_count}</td>
                                <td className="stat-cell">{formatBytes(system.download_size)}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    )
}

export default TopSystemsList
