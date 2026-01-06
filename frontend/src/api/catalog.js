import client from './client'

export const refreshCatalog = async () => {
  const response = await client.post('/api/catalog/refresh')
  return response.data
}



