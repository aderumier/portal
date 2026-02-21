import React from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import CollectionGames from '../components/Catalog/CollectionGames'

const Collection = () => {
    const { id } = useParams()
    const [searchParams] = useSearchParams()
    const searchQuery = searchParams.get('search') || ''

    return <CollectionGames collectionId={id} searchQuery={searchQuery} />
}

export default Collection
