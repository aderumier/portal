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

    const handleSystemClick = (systemId) => {
        navigate(`/systems/${systemId}`) // Assuming this is the route for system details or game list for system
    }

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
                            <th>System Name</th>
                            <th>Game Count</th>
                            <th>Total Downloads</th>
                        </tr>
                    </thead>
                    <tbody>
                        {systems.map((system, index) => (
                            <tr key={system.id} onClick={() => handleSystemClick(system.id)} className="game-row">
                                <td className="rank-col">{index + 1}</td>
                                <td className="game-name-cell">{system.name}</td>
                                <td>{system.gameCount}</td>
                                <td className="stat-cell">{system.download_count}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    )
}

export default TopSystemsList
