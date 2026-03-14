import React, { useState, useEffect } from 'react'
import { useAuth } from '../context/AuthContext'
import { getBugReports, getBugReport } from '../api/bugreports'
import BugReportDetailModal from '../components/BugReport/BugReportDetailModal'
import './BugReports.css'

const BugReports = () => {
  const { isAdmin } = useAuth()
  const [bugReports, setBugReports] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [sortBy, setSortBy] = useState('date')
  const [sortOrder, setSortOrder] = useState('desc')
  const [selectedBugReport, setSelectedBugReport] = useState(null)
  const [showDetailModal, setShowDetailModal] = useState(false)
  const [statusFilter, setStatusFilter] = useState('open')

  useEffect(() => {
    loadBugReports()
  }, [sortBy, sortOrder, statusFilter])

  const loadBugReports = async () => {
    try {
      setLoading(true)
      setError(null)
      const response = await getBugReports(statusFilter, sortBy, sortOrder)
      setBugReports(response.bug_reports || [])
    } catch (err) {
      console.error('Error loading bug reports:', err)
      setError('Failed to load bug reports')
    } finally {
      setLoading(false)
    }
  }

  const handleSort = (column) => {
    if (sortBy === column) {
      // Toggle sort order
      setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc')
    } else {
      setSortBy(column)
      setSortOrder('desc')
    }
  }

  const handleViewDetail = async (id) => {
    try {
      const response = await getBugReport(id)
      setSelectedBugReport(response.bug_report)
      setShowDetailModal(true)
    } catch (err) {
      console.error('Error loading bug report details:', err)
      alert('Failed to load bug report details')
    }
  }

  const handleStatusUpdate = (updatedBugReport) => {
    // Update the bug report in the list
    setBugReports(prevReports =>
      prevReports.map(report =>
        report.id === updatedBugReport.id ? updatedBugReport : report
      )
    )
    setSelectedBugReport(updatedBugReport)
  }

  const formatDate = (dateStr) => {
    if (!dateStr) return 'N/A'
    try {
      const date = new Date(dateStr)
      const day = String(date.getDate()).padStart(2, '0')
      const month = String(date.getMonth() + 1).padStart(2, '0')
      const year = date.getFullYear()
      return `${day}/${month}/${year}`
    } catch (e) {
      return dateStr
    }
  }

  const getStatusBadgeClass = (status) => {
    return `bug-report-status-badge bug-report-status-${status}`
  }

  const getStatusLabel = (status) => {
    if (status === 'notabug') return 'Not a Bug'
    if (status === 'waiting_user_response') return 'Waiting User Response'
    if (status === 'waiting_admin_response') return 'Waiting Admin Response'
    return status.charAt(0).toUpperCase() + status.slice(1).replace(/([A-Z])/g, ' $1')
  }



  if (loading) {
    return (
      <div className="bug-reports-page">
        <div className="bug-reports-loading">Loading bug reports...</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="bug-reports-page">
        <div className="bug-reports-error">{error}</div>
      </div>
    )
  }

  return (
    <div className="bug-reports-page">
      <h1>Bug Reports</h1>

      <div className="bug-reports-status-filters" style={{ marginBottom: '20px', display: 'flex', gap: '10px' }}>
        <button
          className={`filter-btn ${statusFilter === 'all' ? 'active' : ''}`}
          onClick={() => setStatusFilter('all')}
          style={{ padding: '8px 16px', cursor: 'pointer', borderRadius: '4px', border: '1px solid #ccc', backgroundColor: statusFilter === 'all' ? '#007bff' : '#f8f9fa', color: statusFilter === 'all' ? 'white' : 'black' }}
        >
          All
        </button>
        <button
          className={`filter-btn ${statusFilter === 'open' ? 'active' : ''}`}
          onClick={() => setStatusFilter('open')}
          style={{ padding: '8px 16px', cursor: 'pointer', borderRadius: '4px', border: '1px solid #ccc', backgroundColor: statusFilter === 'open' ? '#007bff' : '#f8f9fa', color: statusFilter === 'open' ? 'white' : 'black' }}
        >
          Open
        </button>
        <button
          className={`filter-btn ${statusFilter === 'resolved' ? 'active' : ''}`}
          onClick={() => setStatusFilter('resolved')}
          style={{ padding: '8px 16px', cursor: 'pointer', borderRadius: '4px', border: '1px solid #ccc', backgroundColor: statusFilter === 'resolved' ? '#28a745' : '#f8f9fa', color: statusFilter === 'resolved' ? 'white' : 'black' }}
        >
          Resolved
        </button>
        <button
          className={`filter-btn ${statusFilter === 'notabug' ? 'active' : ''}`}
          onClick={() => setStatusFilter('notabug')}
          style={{ padding: '8px 16px', cursor: 'pointer', borderRadius: '4px', border: '1px solid #ccc', backgroundColor: statusFilter === 'notabug' ? '#dc3545' : '#f8f9fa', color: statusFilter === 'notabug' ? 'white' : 'black' }}
        >
          Not a Bug
        </button>
      </div>

      <div className="bug-reports-table-container">
        <table className="bug-reports-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>Game</th>
              <th>System</th>
              <th>Catalog</th>
              <th onClick={() => handleSort('subject')} className="sortable">
                Subject {sortBy === 'subject' && (sortOrder === 'asc' ? '↑' : '↓')}
              </th>
              <th>User</th>
              <th>Status</th>
              <th onClick={() => handleSort('date')} className="sortable">
                Date {sortBy === 'date' && (sortOrder === 'asc' ? '↑' : '↓')}
              </th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {bugReports.length === 0 ? (
              <tr>
                <td colSpan="9" className="no-bug-reports">
                  No bug reports found
                </td>
              </tr>
            ) : (
              bugReports.map((report) => (
                <tr key={report.id}>
                  <td className="bug-report-id-cell">{report.id}</td>
                  <td className="bug-report-game-cell" title={report.game_name || report.rompath}>
                    {report.game_name || report.rompath}
                  </td>
                  <td className="bug-report-system-cell">{report.system}</td>
                  <td className="bug-report-catalog-cell">{report.catalog}</td>
                  <td className="bug-report-subject-cell" title={report.subject}>
                    {report.subject}
                  </td>
                  <td className="bug-report-user-cell">
                    {report.user?.username || report.user?.id || 'Unknown'}
                  </td>
                  <td className="bug-report-status-cell">
                    <span className={getStatusBadgeClass(report.status)}>
                      {getStatusLabel(report.status)}
                    </span>
                  </td>
                  <td className="bug-report-date-cell">
                    {formatDate(report.created_at)}
                  </td>
                  <td className="bug-report-actions-cell">
                    <button
                      className="bug-report-detail-btn"
                      onClick={() => handleViewDetail(report.id)}
                    >
                      Detail
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <BugReportDetailModal
        isOpen={showDetailModal}
        onClose={() => {
          setShowDetailModal(false)
          setSelectedBugReport(null)
        }}
        bugReport={selectedBugReport}
        onStatusUpdate={handleStatusUpdate}
      />
    </div>
  )
}

export default BugReports

