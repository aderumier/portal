import React from 'react'
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom'
import { AuthProvider } from './context/AuthContext'
import Layout from './components/Layout/Layout'
import Home from './pages/Home'
import Systems from './pages/Systems'
import System from './pages/System'
import Search from './pages/Search'
import Downloads from './pages/Downloads'
import Account from './pages/Account'
import Login from './components/Auth/Login'
import Unauthorized from './components/Auth/Unauthorized'
import ProtectedRoute from './components/Auth/ProtectedRoute'

function App() {
  return (
    <AuthProvider>
      <Router>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/unauthorized" element={<Unauthorized />} />
          <Route path="/" element={<Layout />}>
            <Route index element={<Home />} />
            <Route path="systems" element={<ProtectedRoute><Systems /></ProtectedRoute>} />
            <Route path="system/:id" element={<ProtectedRoute><System /></ProtectedRoute>} />
            <Route path="search" element={<ProtectedRoute><Search /></ProtectedRoute>} />
            <Route path="downloads" element={<ProtectedRoute requireCreator><Downloads /></ProtectedRoute>} />
            <Route path="account" element={<ProtectedRoute><Account /></ProtectedRoute>} />
          </Route>
        </Routes>
      </Router>
    </AuthProvider>
  )
}

export default App

