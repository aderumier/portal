import client from './client'

export const refreshCatalog = async () => {
  const response = await client.post('/api/catalog/refresh')
  return response.data
}

export const getSystems = async (catalogType = 'releases') => {
  const response = await client.get('/api/catalog/systems', {
    params: { catalog_type: catalogType }
  })
  return response.data
}

export const getGames = async (system, page = 1, limit = 12, search = '', catalogType = 'releases') => {
  const response = await client.get(`/api/catalog/games/${system}`, {
    params: { page, limit, search: search || undefined, catalog_type: catalogType }
  })
  return response.data
}

export const searchGames = async (query, page = 1, limit = 12, catalogType = 'releases') => {
  const response = await client.get('/api/catalog/search', {
    params: { q: query, page, limit, catalog_type: catalogType }
  })
  return response.data
}

export const quickSearch = async (query, limit = 20, catalogType = 'releases') => {
  const response = await client.get('/api/catalog/search/quick', {
    params: { q: query, limit, catalog_type: catalogType }
  })
  return response.data
}

export const getGameDetails = async (system, gameId, catalogType = 'releases') => {
  const response = await client.get(`/api/catalog/game/${system}/${encodeURIComponent(gameId)}`, {
    params: { catalog_type: catalogType }
  })
  return response.data
}








