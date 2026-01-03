import React, { useState, useEffect } from 'react'
import { useAuth } from '../context/AuthContext'
import { API_URL } from '../utils/constants'
import client from '../api/client'
import './MediaValidation.css'

const MediaValidation = () => {
  const { isAdmin } = useAuth()
  const [pendingMedia, setPendingMedia] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [filterSystem, setFilterSystem] = useState('')
  const [filterFieldname, setFilterFieldname] = useState('')

  useEffect(() => {
    if (isAdmin) {
      loadPendingMedia()
    }
  }, [isAdmin])

  const loadPendingMedia = async () => {
    try {
      setLoading(true)
      setError(null)
      const response = await client.get('/api/media/pending')
      setPendingMedia(response.data.pending_media || [])
    } catch (err) {
      console.error('Error loading pending media:', err)
      setError('Failed to load pending media')
    } finally {
      setLoading(false)
    }
  }

  const handleValidate = async (system, fieldname, filename) => {
    if (!confirm(`Validate and move ${filename}?`)) {
      return
    }

    try {
      const formData = new FormData()
      formData.append('system', system)
      formData.append('fieldname', fieldname)
      formData.append('filename', filename)

      await client.post('/api/media/validate', formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      })

      alert('Media validated and moved successfully!')
      loadPendingMedia()
    } catch (err) {
      console.error('Error validating media:', err)
      alert(err.response?.data?.detail || 'Failed to validate media')
    }
  }

  const handleDelete = async (system, fieldname, filename) => {
    if (!confirm(`Delete ${filename}?`)) {
      return
    }

    try {
      await client.delete('/api/media/pending', {
        params: {
          system,
          fieldname,
          filename
        }
      })

      alert('Pending media deleted successfully!')
      loadPendingMedia()
    } catch (err) {
      console.error('Error deleting media:', err)
      alert(err.response?.data?.detail || 'Failed to delete media')
    }
  }

  // Get unique systems and fieldnames for filters
  const systems = [...new Set(pendingMedia.map(m => m.system))].sort()
  const fieldnames = [...new Set(pendingMedia.map(m => m.fieldname))].sort()

  // Filter media
  const filteredMedia = pendingMedia.filter(media => {
    if (filterSystem && media.system !== filterSystem) return false
    if (filterFieldname && media.fieldname !== filterFieldname) return false
    return true
  })

  // Group by system and fieldname
  const groupedMedia = filteredMedia.reduce((acc, media) => {
    const key = `${media.system}/${media.fieldname}`
    if (!acc[key]) {
      acc[key] = []
    }
    acc[key].push(media)
    return acc
  }, {})

  if (!isAdmin) {
    return (
      <div className="media-validation-page">
        <div className="media-validation-error">
          <p>You must have Admin role to access media validation.</p>
        </div>
      </div>
    )
  }

  if (loading) {
    return (
      <div className="media-validation-page">
        <div className="media-validation-loading">Loading pending media...</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="media-validation-page">
        <div className="media-validation-error">{error}</div>
      </div>
    )
  }

  return (
    <div className="media-validation-page">
      <h1>Media Validation</h1>
      <p className="media-validation-description">
        Review and validate user-uploaded media files. Validated files will be moved to the game media directories.
      </p>

      <div className="media-validation-filters">
        <div className="filter-group">
          <label>System:</label>
          <select
            value={filterSystem}
            onChange={(e) => setFilterSystem(e.target.value)}
          >
            <option value="">All Systems</option>
            {systems.map(system => (
              <option key={system} value={system}>{system}</option>
            ))}
          </select>
        </div>

        <div className="filter-group">
          <label>Media Type:</label>
          <select
            value={filterFieldname}
            onChange={(e) => setFilterFieldname(e.target.value)}
          >
            <option value="">All Types</option>
            {fieldnames.map(fieldname => (
              <option key={fieldname} value={fieldname}>{fieldname}</option>
            ))}
          </select>
        </div>

        <div className="filter-group">
          <button onClick={loadPendingMedia} className="refresh-button">
            Refresh
          </button>
        </div>
      </div>

      {Object.keys(groupedMedia).length === 0 ? (
        <div className="no-pending-media">
          <p>No pending media files found.</p>
        </div>
      ) : (
        <div className="media-validation-groups">
          {Object.entries(groupedMedia).map(([key, mediaList]) => {
            const [system, fieldname] = key.split('/')
            return (
              <div key={key} className="media-group">
                <h2 className="media-group-title">
                  {system} / {fieldname} ({mediaList.length} file{mediaList.length !== 1 ? 's' : ''})
                </h2>
                <div className="media-list">
                  {mediaList.map((media, index) => (
                    <div key={index} className="media-item">
                      <div className="media-item-preview">
                        <img
                          src={`${API_URL}/api/media/pending-preview/${media.system}/${media.fieldname}/${encodeURIComponent(media.filename)}`}
                          alt={media.filename}
                          onError={(e) => {
                            e.target.style.display = 'none'
                            const placeholder = e.target.nextElementSibling
                            if (placeholder) {
                              placeholder.style.display = 'flex'
                            }
                          }}
                        />
                        <div className="media-item-placeholder" style={{ display: 'none' }}>
                          <i className="fas fa-image"></i>
                        </div>
                      </div>
                      <div className="media-item-info">
                        <div className="media-item-filename">{media.filename}</div>
                        <div className="media-item-meta">
                          Uploaded: {new Date(media.upload_date).toLocaleString()}
                        </div>
                        <div className="media-item-meta">
                          Size: {(media.size / 1024).toFixed(2)} KB
                        </div>
                      </div>
                      <div className="media-item-actions">
                        <button
                          className="validate-button"
                          onClick={() => handleValidate(media.system, media.fieldname, media.filename)}
                        >
                          Validate
                        </button>
                        <button
                          className="delete-button"
                          onClick={() => handleDelete(media.system, media.fieldname, media.filename)}
                        >
                          Delete
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

export default MediaValidation

