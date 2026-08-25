import React, { useMemo, useState } from 'react'

// Column definitions drive both sorting and filtering: each COLUMNS entry carries
// a `sortFn(a, b)` returning the ascending order, and a `filterValue(row)`
// returning the text a per-column search box matches against. Either may be null
// when the column does not support that interaction.

export const cmpText = (a, b) => (a || '').localeCompare(b || '')

export const cmpNum = (a, b) => (a || 0) - (b || 0)

// Numeric-aware string compare, so "1.10.0" lands after "1.9.0" and token ids
// that happen to be numbers do not sort lexicographically.
export const cmpAuto = (a, b) =>
  String(a ?? '').localeCompare(String(b ?? ''), undefined, { numeric: true })

export const cmpDate = (a, b) => {
  const ta = a ? new Date(a).getTime() : 0
  const tb = b ? new Date(b).getTime() : 0
  return (Number.isNaN(ta) ? 0 : ta) - (Number.isNaN(tb) ? 0 : tb)
}

const ipRank = (ip) => {
  const parts = String(ip || '').split('.')
  if (parts.length !== 4) return null
  let rank = 0
  for (const part of parts) {
    if (!/^\d{1,3}$/.test(part)) return null
    const n = Number(part)
    if (n > 255) return null
    rank = rank * 256 + n
  }
  return rank
}

// IPv4 sorts by address value; anything else (IPv6, hostnames, blanks) falls
// back to a plain text compare.
export const cmpIp = (a, b) => {
  const ra = ipRank(a)
  const rb = ipRank(b)
  if (ra !== null && rb !== null) return ra - rb
  return cmpText(a, b)
}

/**
 * Client-side column sorting and filtering for a table.
 *
 * `columns` must be a stable (module-level) array. Pass no `initialKey` to keep
 * the rows in the order the API returned them until a header is clicked.
 */
export const useTableSortFilter = (rows, columns, initialKey = null, initialDir = 'desc') => {
  const [sortKey, setSortKey] = useState(initialKey)
  const [sortDir, setSortDir] = useState(initialDir)
  const [filters, setFilters] = useState({})

  const handleSort = (key) => {
    const col = columns.find(c => c.key === key)
    if (!col?.sortFn) return
    if (sortKey === key) {
      setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    } else {
      setSortKey(key)
      setSortDir('desc')
    }
  }

  const setFilter = (key, value) => setFilters(prev => ({ ...prev, [key]: value }))

  const clearFilters = () => setFilters({})

  const activeFilterCount = columns.filter(
    c => c.filterValue && (filters[c.key] || '').trim()
  ).length

  const displayedRows = useMemo(() => {
    const active = columns
      .filter(c => c.filterValue && (filters[c.key] || '').trim())
      .map(c => [c, filters[c.key].trim().toLowerCase()])

    let list = active.length === 0
      ? rows
      : rows.filter(row =>
          active.every(([col, query]) =>
            String(col.filterValue(row) ?? '').toLowerCase().includes(query)
          )
        )

    const col = columns.find(c => c.key === sortKey)
    if (col?.sortFn) {
      list = [...list].sort((a, b) => sortDir === 'asc' ? col.sortFn(a, b) : col.sortFn(b, a))
    }
    return list
  }, [rows, columns, filters, sortKey, sortDir])

  return {
    sortKey, sortDir, handleSort,
    filters, setFilter, clearFilters, activeFilterCount,
    displayedRows,
  }
}

export const SortIcon = ({ col, sortKey, sortDir }) => {
  if (!col.sortFn) return null
  if (sortKey !== col.key) return <span className="sort-icon sort-icon--idle">↕</span>
  return <span className="sort-icon">{sortDir === 'asc' ? '↑' : '↓'}</span>
}

export const ColumnFilter = ({ col, filters, setFilter }) => {
  if (!col.filterValue) return null
  return (
    <input
      className="column-filter"
      type="search"
      placeholder="Filter…"
      aria-label={`Filter by ${col.label}`}
      value={filters[col.key] || ''}
      onChange={e => setFilter(col.key, e.target.value)}
    />
  )
}
