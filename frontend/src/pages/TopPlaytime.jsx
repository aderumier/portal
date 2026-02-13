import React from 'react'
import TopGamesList from '../components/Catalog/TopGamesList'

const TopPlaytime = () => {
    const formatTime = (seconds) => {
        if (!seconds) return '0h 0m'
        const hours = Math.floor(seconds / 3600)
        const minutes = Math.floor((seconds % 3600) / 60)
        return `${hours}h ${minutes}m`
    }

    return (
        <TopGamesList
            title="Top 100 Playtime"
            sortBy="gametime"
            valueLabel="Time"
            formatValue={formatTime}
        />
    )
}

export default TopPlaytime
