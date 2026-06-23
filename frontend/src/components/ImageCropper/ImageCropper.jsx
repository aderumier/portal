import React, { useEffect, useRef, useState } from 'react'
import Cropper from 'cropperjs'
import 'cropperjs/dist/cropper.css'
import './ImageCropper.css'

// Inline image cropper built on Cropper.js v1 (same library/options as the
// cursorscraper project's image cropper). Renders a crop stage + control bar
// with no surrounding dialog chrome, so it can be embedded inside an existing
// modal (e.g. the media preview lightbox).
//
// Own class names are prefixed `imgcrop-` to avoid colliding with Cropper.js's
// internal `cropper-*` classes (notably its `.cropper-modal` overlay element).
const ImageCropper = ({ imageUrl, filename, onApply, onCancel }) => {
  const imageRef = useRef(null)
  const cropperRef = useRef(null)
  const [saving, setSaving] = useState(false)
  const [keepAspect, setKeepAspect] = useState(false)

  useEffect(() => {
    const image = imageRef.current
    if (!image) return

    const cropper = new Cropper(image, {
      aspectRatio: NaN,        // free aspect ratio
      viewMode: 1,             // crop box cannot exceed the canvas
      dragMode: 'move',
      autoCropArea: 1.0,
      restore: false,
      guides: true,
      center: true,
      highlight: true,
      cropBoxMovable: true,
      cropBoxResizable: true,
      toggleDragModeOnDblclick: false,
      checkCrossOrigin: false,
      checkOrientation: false,
      background: true,
      modal: true,
      responsive: true,
    })
    cropperRef.current = cropper

    return () => {
      cropper.destroy()
      cropperRef.current = null
    }
  }, [imageUrl])

  const handleReset = () => {
    cropperRef.current?.reset()
  }

  const handleAspectToggle = (e) => {
    const checked = e.target.checked
    setKeepAspect(checked)
    const cropper = cropperRef.current
    if (!cropper) return
    if (checked) {
      const data = cropper.getImageData()
      cropper.setAspectRatio(data.naturalWidth / data.naturalHeight)
    } else {
      cropper.setAspectRatio(NaN)
    }
  }

  const handleApply = () => {
    const cropper = cropperRef.current
    if (!cropper) return
    const canvas = cropper.getCroppedCanvas({ imageSmoothingQuality: 'high' })
    if (!canvas) return
    const ext = (filename.split('.').pop() || 'png').toLowerCase()
    const mime = ext === 'jpg' || ext === 'jpeg' ? 'image/jpeg' : ext === 'webp' ? 'image/webp' : 'image/png'
    setSaving(true)
    canvas.toBlob(
      (blob) => {
        if (!blob) { setSaving(false); return }
        Promise.resolve(onApply(blob, { width: canvas.width, height: canvas.height }))
          .finally(() => setSaving(false))
      },
      mime,
      mime === 'image/jpeg' ? 0.95 : undefined
    )
  }

  return (
    <div className="imgcrop">
      <div className="imgcrop-stage">
        <img ref={imageRef} src={imageUrl} alt={filename} crossOrigin="anonymous" />
      </div>
      <div className="imgcrop-toolbar">
        <label className="imgcrop-aspect-toggle">
          <input type="checkbox" checked={keepAspect} onChange={handleAspectToggle} />
          Keep original ratio
        </label>
        <div className="imgcrop-toolbar-actions">
          <button className="imgcrop-btn imgcrop-btn-secondary" onClick={handleReset} disabled={saving}>Reset</button>
          <button className="imgcrop-btn imgcrop-btn-secondary" onClick={onCancel} disabled={saving}>Cancel</button>
          <button className="imgcrop-btn imgcrop-btn-primary" onClick={handleApply} disabled={saving}>
            {saving ? 'Saving…' : 'Apply crop'}
          </button>
        </div>
      </div>
    </div>
  )
}

export default ImageCropper
