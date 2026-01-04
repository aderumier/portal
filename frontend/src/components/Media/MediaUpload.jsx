import React, { useState, useRef } from 'react'
import client from '../../api/client'
import './MediaUpload.css'

const MediaUpload = ({ system, gameId, mediaType, label, onUploadSuccess }) => {
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState(null)
  const [success, setSuccess] = useState(false)
  const fileInputRef = useRef(null)

  const handleFileSelect = async (event) => {
    const file = event.target.files?.[0]
    if (!file) return

    await uploadFile(file)
  }

  const handleDragOver = (e) => {
    e.preventDefault()
    e.stopPropagation()
  }

  const handleDrop = async (e) => {
    e.preventDefault()
    e.stopPropagation()

    const file = e.dataTransfer.files?.[0]
    if (!file) return

    await uploadFile(file)
  }

  const uploadFile = async (file) => {
    // Validate file type
    const allowedTypes = ['image/png', 'image/jpeg', 'image/jpg', 'image/gif', 'image/webp']
    if (!allowedTypes.includes(file.type)) {
      setError('Invalid file type. Please upload an image (PNG, JPG, GIF, or WEBP)')
      return
    }

    // Validate file size (10MB max)
    const maxSize = 10 * 1024 * 1024
    if (file.size > maxSize) {
      setError('File size exceeds 10MB limit')
      return
    }

    setUploading(true)
    setError(null)
    setSuccess(false)

    try {
      const formData = new FormData()
      formData.append('file', file)
      formData.append('system', system)
      formData.append('game_id', gameId)
      formData.append('media_type', mediaType)

      const response = await client.post('/api/media/upload', formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      })

      if (response.data.success) {
        setSuccess(true)
        if (onUploadSuccess) {
          onUploadSuccess()
        }
        // Reset file input
        if (fileInputRef.current) {
          fileInputRef.current.value = ''
        }
      }
    } catch (err) {
      console.error('Upload error:', err)
      setError(err.response?.data?.detail || 'Failed to upload media. Please try again.')
    } finally {
      setUploading(false)
    }
  }

  const handleClick = () => {
    if (fileInputRef.current && !uploading) {
      fileInputRef.current.click()
    }
  }

  return (
    <div 
      className="media-upload-card"
      onDragOver={handleDragOver}
      onDrop={handleDrop}
    >
      <div className="media-upload-content">
        <div className="media-upload-icon">
          <i className="fas fa-cloud-upload-alt"></i>
        </div>
        <div className="media-upload-label">{label}</div>
        <div className="media-upload-hint">Click or drag to upload</div>
        
        {error && (
          <div className="media-upload-error">{error}</div>
        )}
        
        {success && (
          <div className="media-upload-success">
            Uploaded! Pending validation.
          </div>
        )}

        <input
          ref={fileInputRef}
          type="file"
          accept="image/png,image/jpeg,image/jpg,image/gif,image/webp"
          onChange={handleFileSelect}
          style={{ display: 'none' }}
        />

        <button
          className="media-upload-button"
          onClick={handleClick}
          disabled={uploading}
        >
          {uploading ? 'Uploading...' : 'Choose File'}
        </button>
      </div>
    </div>
  )
}

export default MediaUpload


