import React, { useState, useEffect } from 'react'
import client from '../../api/client'
import { submitBugReport } from '../../api/bugreports'
import './BugReportModal.css'

const BugReportModal = ({ isOpen, onClose, gameInfo }) => {
  const [subject, setSubject] = useState('')
  const [description, setDescription] = useState('')
  const [device, setDevice] = useState('')
  const [os, setOs] = useState('')
  const [osVersion, setOsVersion] = useState('')
  const [tokens, setTokens] = useState([])
  const [loading, setLoading] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)
  const [success, setSuccess] = useState(false)

  useEffect(() => {
    if (isOpen) {
      loadTokens()
      // Reset form when modal opens
      setSubject('')
      setDescription('')
      setDevice('')
      setOs('')
      setOsVersion('')
      setError(null)
      setSuccess(false)
    }
  }, [isOpen])

  const loadTokens = async () => {
    try {
      setLoading(true)
      const response = await client.get('/api/users/tokens')
      const activeTokens = response.data.tokens.filter(t => !t.revoked)
      setTokens(activeTokens)
    } catch (err) {
      // Non-guild members can't have tokens; device field is optional so just leave it empty
      setTokens([])
    } finally {
      setLoading(false)
    }
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    
    if (!subject.trim()) {
      setError('Subject is required')
      return
    }
    
    if (!description.trim()) {
      setError('Description is required')
      return
    }

    try {
      setSubmitting(true)
      setError(null)
      
      await submitBugReport({
        rompath: gameInfo.rompath,
        system: gameInfo.system,
        catalog: gameInfo.catalog,
        subject: subject.trim(),
        description: description.trim(),
        device: device || null,
        os: os || null,
        os_version: osVersion.trim() || null
      })
      
      setSuccess(true)
      setTimeout(() => {
        onClose()
        setSuccess(false)
      }, 1500)
    } catch (err) {
      console.error('Error submitting bug report:', err)
      setError(err.response?.data?.detail || 'Failed to submit bug report')
    } finally {
      setSubmitting(false)
    }
  }

  const handleClose = () => {
    if (!submitting) {
      onClose()
    }
  }

  if (!isOpen) return null

  return (
    <div className="bug-report-overlay" onClick={handleClose}>
      <div className="bug-report-modal" onClick={(e) => e.stopPropagation()}>
        <div className="bug-report-header">
          <h2>Report a Bug</h2>
          <button className="bug-report-close" onClick={handleClose} disabled={submitting}>×</button>
        </div>
        <form className="bug-report-form" onSubmit={handleSubmit}>
          <div className="bug-report-content">
            {success ? (
              <div className="bug-report-success">
                Bug report submitted successfully!
              </div>
            ) : (
              <>
                <div className="bug-report-field">
                  <label htmlFor="subject">Subject *</label>
                  <input
                    id="subject"
                    type="text"
                    value={subject}
                    onChange={(e) => setSubject(e.target.value)}
                    placeholder="Brief description of the issue"
                    required
                    disabled={submitting}
                  />
                </div>
                
                <div className="bug-report-field">
                  <label htmlFor="description">Description *</label>
                  <textarea
                    id="description"
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    placeholder="Detailed description of the bug..."
                    rows={6}
                    required
                    disabled={submitting}
                  />
                </div>
                
                <div className="bug-report-field">
                  <label htmlFor="device">Device (Optional)</label>
                  {loading ? (
                    <div className="bug-report-loading">Loading devices...</div>
                  ) : (
                    <select
                      id="device"
                      value={device}
                      onChange={(e) => setDevice(e.target.value)}
                      disabled={submitting}
                    >
                      <option value="">Select a device...</option>
                      {tokens.map((token) => (
                        <option key={token.id} value={token.name}>
                          {token.name}
                        </option>
                      ))}
                    </select>
                  )}
                </div>
                
                <div className="bug-report-field">
                  <label htmlFor="os">OS (Optional)</label>
                  <select
                    id="os"
                    value={os}
                    onChange={(e) => setOs(e.target.value)}
                    disabled={submitting}
                  >
                    <option value="">Select an OS...</option>
                    <option value="batocera">Batocera</option>
                    <option value="retrobat">RetroBat</option>
                  </select>
                </div>
                
                <div className="bug-report-field">
                  <label htmlFor="os_version">OS Version (Optional)</label>
                  <input
                    id="os_version"
                    type="text"
                    value={osVersion}
                    onChange={(e) => setOsVersion(e.target.value)}
                    placeholder="e.g., v40, v39, etc."
                    disabled={submitting}
                  />
                </div>
                
                {error && (
                  <div className="bug-report-error">{error}</div>
                )}
              </>
            )}
          </div>
          
          <div className="bug-report-actions">
            {!success && (
              <>
                <button
                  type="button"
                  className="bug-report-cancel"
                  onClick={handleClose}
                  disabled={submitting}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="bug-report-submit"
                  disabled={submitting}
                >
                  {submitting ? 'Submitting...' : 'Submit'}
                </button>
              </>
            )}
          </div>
        </form>
      </div>
    </div>
  )
}

export default BugReportModal

