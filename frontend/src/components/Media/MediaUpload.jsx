import React, { useState, useRef } from 'react'
import client from '../../api/client'
import './MediaUpload.css'

const MediaUpload = ({ system, gameId, mediaType, label, onUploadSuccess, compact = false }) => {
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

  const handleDoubleClick = () => {
    if (fileInputRef.current && !uploading) {
      fileInputRef.current.click()
    }
  }

  if (compact) {
    // Compact version: just a small upload button
    return (
      <div className="media-upload-compact">
        <input
          ref={fileInputRef}
          type="file"
          accept="image/png,image/jpeg,image/jpg,image/gif,image/webp"
          onChange={handleFileSelect}
          style={{ display: 'none' }}
        />
        <button
          className="media-upload-button-compact"
          onClick={handleClick}
          disabled={uploading}
          title="Upload new image"
        >
          {uploading ? '...' : '📤'}
        </button>
        {error && (
          <div className="media-upload-error-compact">{error}</div>
        )}
        {success && (
          <div className="media-upload-success-compact">✓</div>
        )}
      </div>
    )
  }

  return (
    <div 
      className="media-upload-card"
      onDragOver={handleDragOver}
      onDrop={handleDrop}
      onDoubleClick={handleDoubleClick}
      title="Double-click to upload"
    >
      <div className="media-upload-content">
        <div className="media-upload-icon">
          <i className="fas fa-cloud-upload-alt"></i>
        </div>
        <div className="media-upload-label">{label}</div>
        <div className="media-upload-hint">Double-click to upload</div>
        
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
      </div>
    </div>
  )
}

export default MediaUpload


