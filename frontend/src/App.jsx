import React from 'react'
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom'
import { AuthProvider } from './context/AuthContext'
import { CatalogProvider } from './context/CatalogContext'
import Layout from './components/Layout/Layout'
import Home from './pages/Home'
import Systems from './pages/Systems'
import System from './pages/System'
import Search from './pages/Search'
import GameDetails from './pages/GameDetails'
import Downloads from './pages/Downloads'
import DownloadHistory from './pages/DownloadHistory'
import Devices from './pages/Devices'
import GlobalDownloadHistory from './pages/GlobalDownloadHistory'
import Account from './pages/Account'
import Login from './components/Auth/Login'
import Unauthorized from './components/Auth/Unauthorized'
import ProtectedRoute from './components/Auth/ProtectedRoute'
import MediaValidation from './pages/MediaValidation'
import DownloadQueues from './pages/DownloadQueues'
import UsersStats from './pages/UsersStats'
import ClientsStats from './pages/ClientsStats'
import SystemsConfiguration from './pages/SystemsConfiguration'
import ConnectedClients from './pages/ConnectedClients'
import BugReports from './pages/BugReports'
import Debug from './pages/Debug'
import TopDownloads from './pages/TopDownloads'
import TopPlaycount from './pages/TopPlaycount'
import TopPlaytime from './pages/TopPlaytime'
import TopSystemsList from './pages/TopSystemsList'
import Collections from './pages/Collections'
import Collection from './pages/Collection'
import CurrentTransfers from './pages/CurrentTransfers'
import TorrentTrackerStats from './pages/TorrentTrackerStats'
import Contribute from './pages/Contribute'
import ContributeSystem from './pages/ContributeSystem'

function App() {
  return (
    <AuthProvider>
      <CatalogProvider>
        <Router>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route path="/unauthorized" element={<Unauthorized />} />
            <Route path="/" element={<Layout />}>
              <Route index element={<Home />} />
              <Route path="systems" element={<ProtectedRoute><Systems /></ProtectedRoute>} />
              <Route path="system/:id" element={<ProtectedRoute><System /></ProtectedRoute>} />
              <Route path="contribute" element={<ProtectedRoute requireContribute><Contribute /></ProtectedRoute>} />
              <Route path="contribute/system/:id" element={<ProtectedRoute requireContribute><ContributeSystem /></ProtectedRoute>} />
              <Route path="game/:system/:gameId" element={<ProtectedRoute><GameDetails /></ProtectedRoute>} />
              <Route path="playlist/collections" element={<ProtectedRoute><Collections /></ProtectedRoute>} />
              <Route path="collection/:id" element={<ProtectedRoute><Collection /></ProtectedRoute>} />
              <Route path="playlist/top-downloads" element={<ProtectedRoute><TopDownloads /></ProtectedRoute>} />
              <Route path="playlist/top-playcount" element={<ProtectedRoute><TopPlaycount /></ProtectedRoute>} />
              <Route path="playlist/top-playtime" element={<ProtectedRoute><TopPlaytime /></ProtectedRoute>} />
              <Route path="playlist/top-systems" element={<ProtectedRoute requireAdmin><TopSystemsList /></ProtectedRoute>} />
              <Route path="search" element={<ProtectedRoute><Search /></ProtectedRoute>} />
              <Route path="downloads" element={<ProtectedRoute requireDownload><Downloads /></ProtectedRoute>} />
              <Route path="downloads/history" element={<ProtectedRoute requireDownload><DownloadHistory /></ProtectedRoute>} />
              <Route path="downloads/devices" element={<ProtectedRoute requireDownload><Devices /></ProtectedRoute>} />
              <Route path="account" element={<ProtectedRoute><Account /></ProtectedRoute>} />
              <Route path="downloads/history/all" element={<ProtectedRoute requireAdmin><GlobalDownloadHistory /></ProtectedRoute>} />
              <Route path="users-stats" element={<ProtectedRoute requireAdmin><UsersStats /></ProtectedRoute>} />
              <Route path="clients-stats" element={<ProtectedRoute requireAdmin><ClientsStats /></ProtectedRoute>} />
              <Route path="media-validation" element={<ProtectedRoute requireAdmin><MediaValidation /></ProtectedRoute>} />
              <Route path="bugreports" element={<ProtectedRoute requireAdmin><BugReports /></ProtectedRoute>} />
              <Route path="download-queues" element={<ProtectedRoute requireAdmin><DownloadQueues /></ProtectedRoute>} />
              <Route path="connected-clients" element={<ProtectedRoute requireAdmin><ConnectedClients /></ProtectedRoute>} />
              <Route path="systems-configuration" element={<ProtectedRoute requireAdmin><SystemsConfiguration /></ProtectedRoute>} />
              <Route path="current-transfers" element={<ProtectedRoute requireAdmin><CurrentTransfers /></ProtectedRoute>} />
              <Route path="torrent-tracker-stats" element={<ProtectedRoute requireAdmin><TorrentTrackerStats /></ProtectedRoute>} />
              <Route path="debug" element={<ProtectedRoute requireAdmin><Debug /></ProtectedRoute>} />
            </Route>
          </Routes>
        </Router>
      </CatalogProvider>
    </AuthProvider>
  )
}

export default App

