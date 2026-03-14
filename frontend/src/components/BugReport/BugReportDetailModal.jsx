import React, { useState } from 'react'
import { useAuth } from '../../context/AuthContext'
import { updateBugReportStatus, addBugReportComment } from '../../api/bugreports'
import './BugReportDetailModal.css'

const BugReportDetailModal = ({ isOpen, onClose, bugReport, onStatusUpdate }) => {
  const { isAdmin } = useAuth()
  const [status, setStatus] = useState(bugReport?.status || 'new')
  const [updating, setUpdating] = useState(false)
  const [error, setError] = useState(null)
  const [comments, setComments] = useState(bugReport?.comments || [])
  const [newComment, setNewComment] = useState('')
  const [submittingComment, setSubmittingComment] = useState(false)

  React.useEffect(() => {
    if (bugReport) {
      setStatus(bugReport.status)
      setComments(bugReport?.comments || [])
      setNewComment('')
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

  const handleAddComment = async () => {
    if (!newComment.trim() || !bugReport) return

    try {
      setSubmittingComment(true)
      setError(null)

      const response = await addBugReportComment(bugReport.id, newComment)
      if (response.success && response.comment) {
        setComments([...comments, response.comment])
        setNewComment('')

        // If the backend returned a new status, update local UI state immediately
        if (response.updated_status) {
          setStatus(response.updated_status)
          if (onStatusUpdate) {
            onStatusUpdate({ ...bugReport, status: response.updated_status })
          }
        }
      }
    } catch (err) {
      console.error('Error adding comment:', err)
      setError(err.response?.data?.detail || 'Failed to add comment')
    } finally {
      setSubmittingComment(false)
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
                <label>OS</label>
                <div className="bug-report-detail-value">{bugReport.os || 'N/A'}</div>
              </div>

              <div className="bug-report-detail-field">
                <label>OS Version</label>
                <div className="bug-report-detail-value">{bugReport.os_version || 'N/A'}</div>
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
                      <option value="waiting_user_response">Waiting User Response</option>
                      <option value="waiting_admin_response">Waiting Admin Response</option>
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
                      {bugReport.status === 'notabug' ? 'Not a Bug' : bugReport.status === 'waiting_user_response' ? 'Waiting User Response' : bugReport.status === 'waiting_admin_response' ? 'Waiting Admin Response' : bugReport.status.charAt(0).toUpperCase() + bugReport.status.slice(1)}
                    </span>
                  </div>
                </div>
              )}
            </div>

            {error && (
              <div className="bug-report-detail-error">{error}</div>
            )}

            {/* Comments Section */}
            <div className="bug-report-detail-section bug-report-comments-section" style={{ marginTop: '20px', borderTop: '1px solid #ddd', paddingTop: '20px' }}>
              <h3>Comments</h3>
              <div className="bug-report-comments-list" style={{ marginBottom: '15px' }}>
                {comments.length === 0 ? (
                  <p style={{ fontStyle: 'italic', color: '#666' }}>No comments yet.</p>
                ) : (
                  comments.map(c => (
                    <div key={c.id} className="bug-report-comment-item" style={{ marginBottom: '10px', padding: '10px', backgroundColor: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: '4px' }}>
                      <div className="comment-header" style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '5px', fontSize: '0.9em', color: 'var(--text-secondary)' }}>
                        <strong style={{ color: 'var(--text-primary)' }}>{c.username || c.iduser}</strong>
                        <span>{formatDate(c.created_at)}</span>
                      </div>
                      <div className="comment-body" style={{ whiteSpace: 'pre-wrap', color: 'var(--text-primary)' }}>{c.comment}</div>
                    </div>
                  ))
                )}
              </div>

              <div className="bug-report-add-comment" style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                <textarea
                  value={newComment}
                  onChange={(e) => setNewComment(e.target.value)}
                  placeholder="Add a comment..."
                  rows="3"
                  disabled={submittingComment}
                  style={{ padding: '8px', borderRadius: '4px', border: '1px solid var(--border)', resize: 'vertical', backgroundColor: 'var(--bg-secondary)', color: 'var(--text-primary)' }}
                />
                <button
                  onClick={handleAddComment}
                  disabled={submittingComment || !newComment.trim()}
                  style={{ alignSelf: 'flex-start', padding: '8px 16px', backgroundColor: '#007bff', color: 'white', border: 'none', borderRadius: '4px', cursor: (submittingComment || !newComment.trim()) ? 'not-allowed' : 'pointer', opacity: (submittingComment || !newComment.trim()) ? 0.6 : 1 }}
                >
                  {submittingComment ? 'Posting...' : 'Post Comment'}
                </button>
              </div>
            </div>

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

