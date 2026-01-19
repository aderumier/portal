import React, { useState, useEffect } from 'react'
import { useAuth } from '../context/AuthContext'
import client from '../api/client'
import './ClientsStats.css'

const ClientsStats = () => {
  const { isAdmin } = useAuth()
  const [tokens, setTokens] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [catalogModalOpen, setCatalogModalOpen] = useState(false)
  const [catalogData, setCatalogData] = useState(null)
  const [catalogLoading, setCatalogLoading] = useState(false)
  const [catalogTokenId, setCatalogTokenId] = useState(null)
  const [catalogTokenName, setCatalogTokenName] = useState('')

  useEffect(() => {
    if (isAdmin) {
      loadTokensStats()
    }
  }, [isAdmin])

  const loadTokensStats = async () => {
    try {
      setLoading(true)
      setError(null)
      const response = await client.get('/api/users/tokens/stats')
      setTokens(response.data.tokens || [])
    } catch (err) {
      console.error('Error loading tokens stats:', err)
      setError('Failed to load clients statistics')
    } finally {
      setLoading(false)
    }
  }

  const formatMB = (mb) => {
    if (mb === 0) return '0 MB'
    if (mb < 1024) {
      return `${mb.toFixed(2)} MB`
    }
    return `${(mb / 1024).toFixed(2)} GB`
  }

  const handleDisplayCatalog = async (tokenId, tokenName) => {
    try {
      setCatalogLoading(true)
      setCatalogTokenId(tokenId)
      setCatalogTokenName(tokenName || `Token ${tokenId}`)
      setCatalogModalOpen(true)
      
      const response = await client.get(`/api/download/clients/${tokenId}/catalog`)
      setCatalogData(response.data.catalog || {})
    } catch (err) {
      console.error('Error loading client catalog:', err)
      setCatalogData(null)
      alert(`Error loading catalog: ${err.response?.data?.detail || err.message || 'Unknown error'}`)
    } finally {
      setCatalogLoading(false)
    }
  }

  const handleCloseCatalogModal = () => {
    setCatalogModalOpen(false)
    setCatalogData(null)
    setCatalogTokenId(null)
    setCatalogTokenName('')
  }

  if (!isAdmin) {
    return (
      <div className="clients-stats-page">
        <div className="clients-stats-error">
          <p>You must have Admin role to access clients statistics.</p>
        </div>
      </div>
    )
  }

  if (loading) {
    return (
      <div className="clients-stats-page">
        <div className="clients-stats-loading">Loading clients statistics...</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="clients-stats-page">
        <div className="clients-stats-error">{error}</div>
      </div>
    )
  }

  return (
    <div className="clients-stats-page">
      <h1>Clients Statistics</h1>
      
      <div className="clients-stats-summary">
        <div className="stat-card">
          <div className="stat-value">{tokens.length}</div>
          <div className="stat-label">Total Tokens</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{formatMB(tokens.reduce((sum, t) => sum + (t.p2p_total_download_mb || 0), 0))}</div>
          <div className="stat-label">Total P2P Download</div>
        </div>
        <div className="stat-card">
          <div className="stat-value">{formatMB(tokens.reduce((sum, t) => sum + (t.p2p_total_upload_mb || 0), 0))}</div>
          <div className="stat-label">Total P2P Upload</div>
        </div>
      </div>

      <div className="clients-table-container">
        <table className="clients-table">
          <thead>
            <tr>
              <th>Token ID</th>
              <th>Token Name</th>
              <th>Username</th>
              <th>P2P Download</th>
              <th>P2P Upload</th>
              <th>Games</th>
              <th>Action</th>
            </tr>
          </thead>
          <tbody>
            {tokens.length === 0 ? (
              <tr>
                <td colSpan="7" className="no-tokens">
                  No tokens found
                </td>
              </tr>
            ) : (
              tokens.map((token) => (
                <tr key={token.token_id}>
                  <td className="token-id-cell">
                    <span className="token-id">{token.token_id}</span>
                  </td>
                  <td className="token-name-cell">
                    <span className="token-name">{token.token_name}</span>
                  </td>
                  <td className="username-cell">
                    <span className="username">{token.username || '-'}</span>
                  </td>
                  <td className="p2p-download-mb-cell">
                    <span className="p2p-download-mb">{formatMB(token.p2p_total_download_mb || 0)}</span>
                  </td>
                  <td className="p2p-upload-mb-cell">
                    <span className="p2p-upload-mb">{formatMB(token.p2p_total_upload_mb || 0)}</span>
                  </td>
                  <td className="p2p-game-count-cell">
                    <span className="p2p-game-count">{token.p2p_game_count || 0}</span>
                  </td>
                  <td className="action-cell">
                    <button
                      className="display-catalog-btn"
                      onClick={() => handleDisplayCatalog(token.token_id, token.token_name)}
                      title="Display P2P catalog"
                    >
                      Display Catalog
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {catalogModalOpen && (
        <div className="catalog-modal-overlay" onClick={handleCloseCatalogModal}>
          <div className="catalog-modal" onClick={(e) => e.stopPropagation()}>
            <div className="catalog-modal-header">
              <h2>P2P Catalog - {catalogTokenName}</h2>
              <button className="catalog-modal-close" onClick={handleCloseCatalogModal}>×</button>
            </div>
            <div className="catalog-modal-content">
              {catalogLoading ? (
                <div className="catalog-loading">Loading catalog...</div>
              ) : catalogData && Object.keys(catalogData).length > 0 ? (
                <CatalogTree catalog={catalogData} />
              ) : (
                <div className="catalog-empty">No catalog data available</div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// Recursive component for displaying the catalog tree
const CatalogTree = ({ catalog, path = '' }) => {
  const [expanded, setExpanded] = useState({})

  const toggleExpanded = (key) => {
    setExpanded(prev => ({
      ...prev,
      [key]: !prev[key]
    }))
  }

  const renderNode = (node, name, currentPath) => {
    const fullPath = currentPath ? `${currentPath}/${name}` : name
    const isFile = node.__is_file__ === true
    const hasChildren = Object.keys(node).filter(k => k !== '__is_file__').length > 0
    const isExpanded = expanded[fullPath] || false

    if (isFile && !hasChildren) {
      // Leaf file node
      return (
        <div key={fullPath} className="tree-node tree-file">
          <span className="tree-file-icon">📄</span>
          <span className="tree-name">{name}</span>
        </div>
      )
    } else {
      // Folder node
      return (
        <div key={fullPath} className="tree-node tree-folder">
          <div 
            className="tree-folder-header" 
            onClick={() => toggleExpanded(fullPath)}
            style={{ cursor: 'pointer' }}
          >
            <span className="tree-folder-icon">
              {isExpanded ? '📂' : '📁'}
            </span>
            <span className="tree-name">{name}</span>
          </div>
          {isExpanded && hasChildren && (
            <div className="tree-children">
              {Object.entries(node)
                .filter(([key]) => key !== '__is_file__')
                .sort(([a], [b]) => {
                  // Sort: folders first, then files
                  const aIsFile = node[a].__is_file__ === true && Object.keys(node[a]).filter(k => k !== '__is_file__').length === 0
                  const bIsFile = node[b].__is_file__ === true && Object.keys(node[b]).filter(k => k !== '__is_file__').length === 0
                  if (aIsFile !== bIsFile) {
                    return aIsFile ? 1 : -1
                  }
                  return a.localeCompare(b)
                })
                .map(([childName, childNode]) => 
                  renderNode(childNode, childName, fullPath)
                )}
            </div>
          )}
        </div>
      )
    }
  }

  if (typeof catalog === 'object' && catalog !== null && !catalog.__is_file__) {
    // Root level - render systems
    return (
      <div className="catalog-tree">
        {Object.keys(catalog)
          .sort()
          .map(system => (
            <div key={system} className="tree-system">
              <div 
                className="tree-system-header"
                onClick={() => toggleExpanded(system)}
                style={{ cursor: 'pointer', fontWeight: 'bold' }}
              >
                <span className="tree-folder-icon">
                  {expanded[system] ? '📂' : '📁'}
                </span>
                <span className="tree-name">{system}</span>
              </div>
              {expanded[system] && (
                <div className="tree-children">
                  {Object.entries(catalog[system])
                    .filter(([key]) => key !== '__is_file__')
                    .sort(([a], [b]) => {
                      const aIsFile = catalog[system][a].__is_file__ === true && Object.keys(catalog[system][a]).filter(k => k !== '__is_file__').length === 0
                      const bIsFile = catalog[system][b].__is_file__ === true && Object.keys(catalog[system][b]).filter(k => k !== '__is_file__').length === 0
                      if (aIsFile !== bIsFile) {
                        return aIsFile ? 1 : -1
                      }
                      return a.localeCompare(b)
                    })
                    .map(([childName, childNode]) => 
                      renderNode(childNode, childName, system)
                    )}
                </div>
              )}
            </div>
          ))}
      </div>
    )
  }

  return null
}

export default ClientsStats

