import React from 'react'
import TopGamesList from '../components/Catalog/TopGamesList'

const TopDownloads = () => {
    return (
        <TopGamesList
            title="Top 100 Downloads"
            sortBy="download_count"
            valueLabel="Downloads"
        />
    )
}

export default TopDownloads
