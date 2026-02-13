import React from 'react'
import TopGamesList from '../components/Catalog/TopGamesList'

const TopPlaycount = () => {
    return (
        <TopGamesList
            title="Top 100 Most Played"
            sortBy="playcount"
            valueLabel="Plays"
        />
    )
}

export default TopPlaycount
