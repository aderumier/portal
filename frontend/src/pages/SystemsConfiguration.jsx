import React, { useState, useEffect } from 'react'
import client from '../api/client'
import './SystemsConfiguration.css'

const SystemsConfiguration = () => {
  const [systems, setSystems] = useState([])
  const [loading, setLoading] = useState(true)
  const [importing, setImporting] = useState(false)
  const [message, setMessage] = useState(null)
  const [imageErrors, setImageErrors] = useState(new Set())

  useEffect(() => {
    loadSystems()
  }, [])

  const loadSystems = async () => {
    try {
      setLoading(true)
      const response = await client.get('/api/admin/systems')
      setSystems(response.data.systems || [])
    } catch (error) {
      console.error('Error loading systems:', error)
      setMessage({ type: 'error', text: 'Failed to load systems' })
    } finally {
      setLoading(false)
    }
  }

  const handleImport = async () => {
    try {
      setImporting(true)
      setMessage(null)
      const response = await client.post('/api/admin/systems/import')
      setMessage({
        type: 'success',
        text: `Import completed: ${response.data.imported} imported, ${response.data.updated} updated, ${response.data.total} total`
      })
      await loadSystems()
    } catch (error) {
      console.error('Error importing systems:', error)
      setMessage({
        type: 'error',
        text: error.response?.data?.detail || 'Failed to import systems'
      })
    } finally {
      setImporting(false)
    }
  }

  const handleToggleEnabled = async (systemId, currentEnabled) => {
    try {
      await client.put(`/api/admin/systems/${systemId}`, {
        enabled: !currentEnabled
      })
      await loadSystems()
      setMessage({
        type: 'success',
        text: `System ${systemId} ${!currentEnabled ? 'enabled' : 'disabled'}`
      })
    } catch (error) {
      console.error('Error updating system:', error)
      setMessage({
        type: 'error',
        text: 'Failed to update system'
      })
    }
  }

  const handleToggleDownloadEnabled = async (systemId, currentDownloadEnabled) => {
    try {
      await client.put(`/api/admin/systems/${systemId}`, {
        download_enabled: !currentDownloadEnabled
      })
      await loadSystems()
      setMessage({
        type: 'success',
        text: `System ${systemId} downloads ${!currentDownloadEnabled ? 'enabled' : 'disabled'}`
      })
    } catch (error) {
      console.error('Error updating system:', error)
      setMessage({
        type: 'error',
        text: 'Failed to update system'
      })
    }
  }

  const handleFieldChange = (systemId, field, value) => {
    // Update local state immediately for responsive UI
    setSystems(prevSystems =>
      prevSystems.map(system =>
        system.id === systemId ? { ...system, [field]: value } : system
      )
    )
  }

  const handleFieldBlur = async (systemId, field, value) => {
    try {
      await client.put(`/api/admin/systems/${systemId}`, {
        [field]: value
      })
      // Optionally show a subtle success message or just update silently
      // Don't reload all systems to avoid refreshing the grid
    } catch (error) {
      console.error('Error updating system:', error)
      // Revert the change on error
      await loadSystems()
      setMessage({
        type: 'error',
        text: 'Failed to update system'
      })
    }
  }

  const handleImageUpload = async (systemId, event) => {
    const file = event.target.files[0]
    if (!file) return

    // Validate file type
    const allowedTypes = ['image/png', 'image/jpeg', 'image/jpg', 'image/gif', 'image/webp']
    if (!allowedTypes.includes(file.type)) {
      setMessage({
        type: 'error',
        text: 'Invalid file type. Please upload PNG, JPG, GIF, or WebP image.'
      })
      return
    }

    try {
      const formData = new FormData()
      formData.append('file', file)

      const response = await client.post(
        `/api/admin/systems/${systemId}/image`,
        formData,
        {
          headers: {
            'Content-Type': 'multipart/form-data'
          }
        }
      )

      setMessage({
        type: 'success',
        text: response.data.message || 'Image uploaded successfully'
      })

      // Remove from error set so image will be shown
      setImageErrors(prev => {
        const newSet = new Set(prev)
        newSet.delete(systemId)
        return newSet
      })

      // Reset file input
      event.target.value = ''
      
      // Force image reload by adding timestamp
      setTimeout(() => {
        const img = document.querySelector(`img[alt="${systemId}"]`)
        if (img) {
          const url = new URL(img.src)
          url.searchParams.set('t', Date.now())
          img.src = url.toString()
        }
      }, 100)
    } catch (error) {
      console.error('Error uploading image:', error)
      setMessage({
        type: 'error',
        text: error.response?.data?.detail || 'Failed to upload image'
      })
      event.target.value = ''
    }
  }

  const getSystemImageUrl = (systemId) => {
    // Get base system ID (remove suffixes)
    let imageId = systemId
    if (systemId.endsWith('_batocera')) {
      imageId = systemId.slice(0, -9)
    } else if (systemId.endsWith('_retrobat')) {
      imageId = systemId.slice(0, -9)
    } else if (systemId.endsWith('_lite')) {
      imageId = systemId.slice(0, -5)
    }
    return `/systems_logos/${imageId}.webp`
  }

  const handleImageDoubleClick = (systemId, event) => {
    // Trigger file input click
    const fileInput = event.currentTarget.querySelector('input[type="file"]')
    if (fileInput) {
      fileInput.click()
    }
  }

  if (loading) {
    return <div className="systems-config-loading">Loading systems...</div>
  }

  return (
    <div className="systems-config">
      <div className="systems-config-header">
        <h1>Systems Configuration</h1>
        <button
          onClick={handleImport}
          disabled={importing}
          className="import-btn"
        >
          {importing ? 'Importing...' : 'Import Systems'}
        </button>
      </div>

      {message && (
        <div className={`message message-${message.type}`}>
          {message.text}
        </div>
      )}

      <div className="systems-config-table-container">
        <table className="systems-config-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>Image</th>
              <th>Full Name</th>
              <th>Hardware</th>
              <th>Manufacturer</th>
              <th>Release</th>
              <th>Batocera System</th>
              <th>Retrobat System</th>
              <th>Enabled</th>
              <th>Download Enabled</th>
            </tr>
          </thead>
          <tbody>
            {systems.map((system) => (
              <tr key={system.id}>
                <td>{system.id}</td>
                <td className="system-image-cell">
                  <div 
                    className="system-image-upload"
                    onDoubleClick={(e) => handleImageDoubleClick(system.id, e)}
                    title="Double-click to upload image"
                  >
                    <input
                      type="file"
                      accept="image/png,image/jpeg,image/jpg,image/gif,image/webp"
                      onChange={(e) => handleImageUpload(system.id, e)}
                      style={{ display: 'none' }}
                      id={`image-input-${system.id}`}
                    />
                    {!imageErrors.has(system.id) ? (
                      <img
                        src={getSystemImageUrl(system.id)}
                        alt={system.id}
                        className="system-image-preview"
                        onError={(e) => {
                          setImageErrors(prev => new Set(prev).add(system.id))
                        }}
                      />
                    ) : null}
                    {imageErrors.has(system.id) && (
                      <div className="system-image-placeholder">
                        <span>Double-click to upload</span>
                      </div>
                    )}
                  </div>
                </td>
                <td>
                  <input
                    type="text"
                    value={system.fullname || ''}
                    onChange={(e) => handleFieldChange(system.id, 'fullname', e.target.value)}
                    onBlur={(e) => handleFieldBlur(system.id, 'fullname', e.target.value)}
                    className="editable-input"
                  />
                </td>
                <td>
                  <input
                    type="text"
                    value={system.hardware || ''}
                    onChange={(e) => handleFieldChange(system.id, 'hardware', e.target.value)}
                    onBlur={(e) => handleFieldBlur(system.id, 'hardware', e.target.value)}
                    className="editable-input"
                  />
                </td>
                <td>
                  <input
                    type="text"
                    value={system.manufacturer || ''}
                    onChange={(e) => handleFieldChange(system.id, 'manufacturer', e.target.value)}
                    onBlur={(e) => handleFieldBlur(system.id, 'manufacturer', e.target.value)}
                    className="editable-input"
                  />
                </td>
                <td>
                  <input
                    type="text"
                    value={system.release || ''}
                    onChange={(e) => handleFieldChange(system.id, 'release', e.target.value)}
                    onBlur={(e) => handleFieldBlur(system.id, 'release', e.target.value)}
                    className="editable-input"
                  />
                </td>
                <td>
                  <input
                    type="text"
                    value={system.batocera_system || ''}
                    onChange={(e) => handleFieldChange(system.id, 'batocera_system', e.target.value)}
                    onBlur={(e) => handleFieldBlur(system.id, 'batocera_system', e.target.value)}
                    className="editable-input"
                  />
                </td>
                <td>
                  <input
                    type="text"
                    value={system.retrobat_system || ''}
                    onChange={(e) => handleFieldChange(system.id, 'retrobat_system', e.target.value)}
                    onBlur={(e) => handleFieldBlur(system.id, 'retrobat_system', e.target.value)}
                    className="editable-input"
                  />
                </td>
                <td>
                  <button
                    onClick={() => handleToggleEnabled(system.id, system.enabled)}
                    className={`toggle-btn ${system.enabled ? 'enabled' : 'disabled'}`}
                  >
                    {system.enabled ? 'Enabled' : 'Disabled'}
                  </button>
                </td>
                <td>
                  <button
                    onClick={() => handleToggleDownloadEnabled(system.id, system.download_enabled !== false)}
                    className={`toggle-btn ${system.download_enabled !== false ? 'enabled' : 'disabled'}`}
                  >
                    {system.download_enabled !== false ? 'Enabled' : 'Disabled'}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default SystemsConfiguration

