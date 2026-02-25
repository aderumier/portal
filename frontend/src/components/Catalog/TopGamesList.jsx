import React, { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { getTopDownloads } from '../../api/catalog'
import { useCatalog } from '../../context/CatalogContext'
import { useDownloadWithToken } from '../../hooks/useDownloadWithToken'
import TokenSelectorDropdown from '../TokenSelector/TokenSelectorDropdown'
import WarningModal from '../WarningModal/WarningModal'
import { getMediaUrl } from '../../utils/constants'
import { useAuth } from '../../context/AuthContext'
import './TopGamesList.css'

const TopGamesList = ({ title, sortBy, valueLabel, formatValue }) => {
    const { catalogType } = useCatalog()
    const [games, setGames] = useState([])
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState(null)
    const [sortColumn, setSortColumn] = useState(sortBy)
    const [sortDirection, setSortDirection] = useState('desc')
    const navigate = useNavigate()
    const { addToQueue, handleTokenSelected, cancelTokenSelection, showTokenSelector, pendingGameId, showOldClientWarning, setShowOldClientWarning } = useDownloadWithToken()
    const { isDownload, isFastDownload } = useAuth()

    useEffect(() => {
        loadTopGames()
    }, [catalogType, sortBy])

    const loadTopGames = async () => {
        try {
            setLoading(true)
            const data = await getTopDownloads(100, catalogType, sortBy)
            setGames(data)
        } catch (err) {
            console.error('Error loading top games:', err)
            setError('Failed to load top games')
        } finally {
            setLoading(false)
        }
    }

    const handleDownload = async (game, e) => {
        e.stopPropagation()
        try {
            const result = await addToQueue(game.id, game.system)
            if (result && result.success) {
                alert('Game added to download queue!')
            }
        } catch (error) {
            console.error('Error adding to download queue:', error)
            const requiresSelection = error.response?.headers?.['x-requires-token-selection'] === 'true' ||
                error.response?.headers?.['X-Requires-Token-Selection'] === 'true' ||
                error.response?.data?.detail?.includes('Multiple tokens found')

            if (!requiresSelection) {
                const errorMsg = error.response?.data?.detail || 'Failed to add game to download queue. Please try again.'
                alert(errorMsg)
            }
        }
    }

    const handleGameClick = (game) => {
        let gameId = game.id.replace(/^\.\//, '')
        if (gameId.startsWith(`${game.system}/`)) {
            gameId = gameId.substring(game.system.length + 1)
        }
        navigate(`/game/${game.system}/${encodeURIComponent(gameId)}`)
    }

    const handleSort = (column) => {
        if (sortColumn === column) {
            setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc')
        } else {
            setSortColumn(column)
            setSortDirection('desc') // Default desc for stats
        }
    }

    const sortedGames = [...games].sort((a, b) => {
        let valA = a[sortColumn]
        let valB = b[sortColumn]

        // Handle string comparisons for name/system
        if (sortColumn === 'name' || sortColumn === 'systemName') {
            valA = (valA || '').toLowerCase()
            valB = (valB || '').toLowerCase()
            return sortDirection === 'asc' ? valA.localeCompare(valB) : valB.localeCompare(valA)
        }

        // Handle numeric comparisons
        if (valA == null) valA = 0
        if (valB == null) valB = 0

        return sortDirection === 'asc' ? valA - valB : valB - valA
    })

    // Helper to format values if needed (e.g. seconds to time)
    const getDisplayValue = (game) => {
        const val = game[sortBy]
        return formatValue ? formatValue(val) : val
    }

    if (loading) return <div className="loading">Loading top games...</div>
    if (error) return <div className="error">{error}</div>

    return (
        <div className="top-games-page">
            <TokenSelectorDropdown
                isOpen={showTokenSelector}
                onClose={cancelTokenSelection}
                onSelect={handleTokenSelected}
                gameId={pendingGameId}
            />
            <WarningModal
                isOpen={showOldClientWarning}
                onClose={() => setShowOldClientWarning(false)}
                title="Update Required"
                message="Your client version is too old. Please update your client to download games."
            />
            <h1>{title}</h1>

            <div className="games-table-container">
                <table className="games-table">
                    <thead>
                        <tr>
                            <th className="rank-col">#</th>
                            <th>Image</th>
                            <th className="sortable" onClick={() => handleSort('name')}>
                                Game Name {sortColumn === 'name' && (sortDirection === 'asc' ? '↑' : '↓')}
                            </th>
                            <th className="sortable" onClick={() => handleSort('systemName')}>
                                System {sortColumn === 'systemName' && (sortDirection === 'asc' ? '↑' : '↓')}
                            </th>
                            <th className="sortable" onClick={() => handleSort(sortBy)}>
                                {valueLabel} {sortColumn === sortBy && (sortDirection === 'asc' ? '↑' : '↓')}
                            </th>
                            {(isDownload || isFastDownload) && <th>Action</th>}
                        </tr>
                    </thead>
                    <tbody>
                        {sortedGames.map((game, index) => (
                            <tr key={`${game.system}-${game.id}`} onClick={() => handleGameClick(game)} className="game-row">
                                <td className="rank-col">{index + 1}</td>
                                <td className="game-image-cell">
                                    {game.image ? (
                                        <img
                                            src={getMediaUrl(game.image)}
                                            alt={game.name}
                                            className="game-list-thumbnail"
                                            loading="lazy"
                                        />
                                    ) : (
                                        <div className="no-image-placeholder">No Image</div>
                                    )}
                                </td>
                                <td className="game-name-cell">{game.name}</td>
                                <td>{game.systemName}</td>
                                <td className="stat-cell">{getDisplayValue(game)}</td>
                                {(isDownload || isFastDownload) && (
                                    <td>
                                        <button
                                            className="download-btn"
                                            onClick={(e) => handleDownload(game, e)}
                                        >
                                            Download
                                        </button>
                                    </td>
                                )}
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    )
}

export default TopGamesList
