import React, { useState } from 'react'
import { useAuth } from '../../context/AuthContext'
import { updateBugReportStatus } from '../../api/bugreports'
import './BugReportDetailModal.css'

const BugReportDetailModal = ({ isOpen, onClose, bugReport, onStatusUpdate }) => {
  const { isAdmin } = useAuth()
  const [status, setStatus] = useState(bugReport?.status || 'new')
  const [updating, setUpdating] = useState(false)
  const [error, setError] = useState(null)

  React.useEffect(() => {
    if (bugReport) {
      setStatus(bugReport.status)
      setError(null)
    }
  }, [bugReport])

  const handleStatusChange = async () => {
    if (!isAdmin || !bugReport) return
    
    if (status === bugReport.status) {
      return // No change
    }

    try {
      setUpdating(true)
      setError(null)
      
      const response = await updateBugReportStatus(bugReport.id, status)
      
      if (response.success && onStatusUpdate) {
        onStatusUpdate(response.bug_report)
      }
    } catch (err) {
      console.error('Error updating bug report status:', err)
      setError(err.response?.data?.detail || 'Failed to update status')
    } finally {
      setUpdating(false)
    }
  }

  const handleClose = () => {
    if (!updating) {
      onClose()
    }
  }

  if (!isOpen || !bugReport) return null

  const formatDate = (dateStr) => {
    if (!dateStr) return 'N/A'
    try {
      return new Date(dateStr).toLocaleString()
    } catch (e) {
      return dateStr
    }
  }

  return (
    <div className="bug-report-detail-overlay" onClick={handleClose}>
      <div className="bug-report-detail-modal" onClick={(e) => e.stopPropagation()}>
        <div className="bug-report-detail-header">
          <h2>Bug Report Details</h2>
          <button className="bug-report-detail-close" onClick={handleClose} disabled={updating}>×</button>
        </div>
        
        <div className="bug-report-detail-content">
          <div className="bug-report-detail-section">
            {/* Subject at the beginning */}
            <div className="bug-report-detail-field">
              <label>Subject</label>
              <div className="bug-report-detail-value bug-report-detail-subject">
                {bugReport.subject}
              </div>
            </div>
            
            {/* Description next */}
            <div className="bug-report-detail-field">
              <label>Description</label>
              <div className="bug-report-detail-value bug-report-detail-description">
                {bugReport.description}
              </div>
            </div>
            
            {/* Two-column layout for other fields */}
            <div className="bug-report-detail-fields-grid">
              <div className="bug-report-detail-field">
                <label>Game</label>
                <div className="bug-report-detail-value">
                  <div className="bug-report-game-name">{bugReport.game_name || bugReport.rompath}</div>
                  <div className="bug-report-rompath" title={bugReport.rompath}>
                    {bugReport.rompath}
                  </div>
                </div>
              </div>
              
              <div className="bug-report-detail-field">
                <label>System</label>
                <div className="bug-report-detail-value">{bugReport.system}</div>
              </div>
              
              <div className="bug-report-detail-field">
                <label>Catalog</label>
                <div className="bug-report-detail-value">{bugReport.catalog}</div>
              </div>
              
              <div className="bug-report-detail-field">
                <label>Device</label>
                <div className="bug-report-detail-value">{bugReport.device || 'N/A'}</div>
              </div>
              
              <div className="bug-report-detail-field">
                <label>User</label>
                <div className="bug-report-detail-value">
                  {bugReport.user?.username || bugReport.user?.id || 'Unknown'}
                </div>
              </div>
              
              <div className="bug-report-detail-field">
                <label>Created At</label>
                <div className="bug-report-detail-value">{formatDate(bugReport.created_at)}</div>
              </div>
              
              {isAdmin && (
                <div className="bug-report-detail-field bug-report-detail-field-full">
                  <label>Status</label>
                  <div className="bug-report-detail-status-controls">
                    <select
                      value={status}
                      onChange={(e) => setStatus(e.target.value)}
                      disabled={updating}
                      className="bug-report-detail-status-select"
                    >
                      <option value="new">New</option>
                      <option value="notabug">Not a Bug</option>
                      <option value="resolved">Resolved</option>
                    </select>
                    {status !== bugReport.status && (
                      <button
                        className="bug-report-detail-save-status"
                        onClick={handleStatusChange}
                        disabled={updating}
                      >
                        {updating ? 'Saving...' : 'Save Status'}
                      </button>
                    )}
                  </div>
                </div>
              )}
              
              {!isAdmin && (
                <div className="bug-report-detail-field bug-report-detail-field-full">
                  <label>Status</label>
                  <div className="bug-report-detail-value">
                    <span className={`bug-report-status-badge bug-report-status-${bugReport.status}`}>
                      {bugReport.status.charAt(0).toUpperCase() + bugReport.status.slice(1)}
                    </span>
                  </div>
                </div>
              )}
            </div>
            
            {error && (
              <div className="bug-report-detail-error">{error}</div>
            )}
          </div>
        </div>
        
        <div className="bug-report-detail-actions">
          <button
            className="bug-report-detail-close-btn"
            onClick={handleClose}
            disabled={updating}
          >
            Close
          </button>
        </div>
      </div>
    </div>
  )
}

export default BugReportDetailModal

