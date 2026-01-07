import React from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import SystemGames from '../components/Catalog/SystemGames'

const System = () => {
  const { id } = useParams()
  const [searchParams] = useSearchParams()
  const searchQuery = searchParams.get('search') || ''

  // systemName will be derived from the games API response in SystemGames component
  return <SystemGames systemId={id} searchQuery={searchQuery} />
}

export default System


