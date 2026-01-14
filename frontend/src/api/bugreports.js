import client from './client'

export const submitBugReport = async (data) => {
  const response = await client.post('/api/bugreports', data)
  return response.data
}

export const getBugReports = async (sortBy = null, sortOrder = 'desc') => {
  const params = {}
  if (sortBy) {
    params.sort_by = sortBy
  }
  if (sortOrder) {
    params.sort_order = sortOrder
  }
  const response = await client.get('/api/bugreports', { params })
  return response.data
}

export const getBugReport = async (id) => {
  const response = await client.get(`/api/bugreports/${id}`)
  return response.data
}

export const updateBugReportStatus = async (id, status) => {
  const response = await client.patch(`/api/bugreports/${id}`, { status })
  return response.data
}

