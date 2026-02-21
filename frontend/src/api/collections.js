import client from './client'
import { setMediaVersion } from '../utils/constants'

export const getCollections = async (catalogType = 'releases') => {
  const response = await client.get('/api/collections', {
    params: { catalog_type: catalogType }
  })
  const data = response.data
  return data
}

export const getCollectionGames = async (collectionId, page = 1, limit = 12, search = '', catalogType = 'releases') => {
  const response = await client.get(`/api/collections/${collectionId}`, {
    params: { page, limit, search: search || undefined, catalog_type: catalogType }
  })
  return response.data
}
