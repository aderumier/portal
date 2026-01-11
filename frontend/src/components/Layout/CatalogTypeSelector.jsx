import React from 'react'
import { useCatalog } from '../../context/CatalogContext'
import './CatalogTypeSelector.css'

const CatalogTypeSelector = () => {
  const { catalogType, setCatalogType, releasesEnabled, loading } = useCatalog()

  const handleChange = (e) => {
    const newType = e.target.value
    setCatalogType(newType)
  }

  if (loading) {
    return null // Don't render until preference is loaded
  }

  // If Releases catalog is disabled, don't show the selector (only WIP available)
  if (!releasesEnabled) {
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
