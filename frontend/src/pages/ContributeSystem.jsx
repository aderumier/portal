import React from 'react'
import { useParams } from 'react-router-dom'
import ContributeGamesList from '../components/Catalog/ContributeGamesList'

const ContributeSystem = () => {
  const { id } = useParams()
  return <ContributeGamesList systemId={id} />
}

export default ContributeSystem
