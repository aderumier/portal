import React, { useEffect } from 'react'
import { useAuth } from '../../context/AuthContext'

const Login = () => {
  const { login } = useAuth()

  useEffect(() => {
    login()
  }, [login])

  return (
    <div style={{ 
      display: 'flex', 
      justifyContent: 'center', 
      alignItems: 'center', 
      height: '100vh',
      flexDirection: 'column',
      gap: '1rem'
    }}>
      <h1>Redirecting to Discord...</h1>
      <p>Please wait while we redirect you to Discord for authentication.</p>
    </div>
  )
}

export default Login














