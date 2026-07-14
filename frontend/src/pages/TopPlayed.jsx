import React from 'react'
import TopGamesList from '../components/Catalog/TopGamesList'

const formatTime = (seconds) => {
    if (!seconds) return '0h 0m'
    const hours = Math.floor(seconds / 3600)
    const minutes = Math.floor((seconds % 3600) / 60)
    return `${hours}h ${minutes}m`
}

const formatScore = (score) => (score == null ? '-' : Number(score).toFixed(3))

// Ranked by a TOPSIS score combining how many people played the game, how often, and for how
// long, so that no single criterion (nor any single player's machine) can own the chart. Every
// column is sortable if you want to look at one criterion on its own.
const TopPlayed = () => {
    return (
        <TopGamesList
            title="Top Played Games"
            sortBy="topsis_score"
            columns={[
                { key: 'topsis_score', label: 'Score', format: formatScore },
                { key: 'player_count', label: 'Players' },
                { key: 'playcount', label: 'Plays' },
                { key: 'gametime', label: 'Playtime', format: formatTime },
            ]}
        />
    )
}

export default TopPlayed
