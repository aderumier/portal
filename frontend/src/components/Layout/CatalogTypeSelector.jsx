import React from 'react'
import { useCatalog } from '../../context/CatalogContext'
import './CatalogTypeSelector.css'

const CatalogTypeSelector = () => {
  const { catalogType, setCatalogType, canViewReleases, canViewWip, loading } = useCatalog()

  const handleChange = (e) => {
    setCatalogType(e.target.value)
  }

  if (loading) {
    return null
  }

  // Only one catalog accessible — no point showing a selector
  if (!canViewReleases || !canViewWip) {
    return null
  }

  return (
    <div className="catalog-type-selector">
      <select
        value={catalogType}
        onChange={handleChange}
        className="catalog-type-select"
        aria-label="Select catalog type"
      >
        <option value="wip">WIP</option>
        <option value="releases">Releases</option>
      </select>
    </div>
  )
}

export default CatalogTypeSelector
