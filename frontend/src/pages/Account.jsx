import React from 'react'
import { useAuth } from '../context/AuthContext'
import './Account.css'

const Account = () => {
  const { user } = useAuth()

  return (
    <div className="account-page">
      <h1>Account Settings</h1>

      <div className="account-section">
        <h2>User Information</h2>
        <div className="user-info">
          <p><strong>Username:</strong> {user?.username}</p>
          <p><strong>User ID:</strong> {user?.id}</p>
          <p><strong>Guild Member:</strong> {user?.is_guild_member ? 'Yes' : 'No'}</p>
          <p><strong>Download Role:</strong> {user?.download_role_name || user?.fastdownload_role_name || 'No'}</p>
          {user?.fastdownload_role_name && (
            <p><strong>Fast Download Role:</strong> {user?.fastdownload_role_name}</p>
          )}
          <p><strong>Admin Role:</strong> {user?.admin_role_name || 'No'}</p>
        </div>
      </div>
    </div>
  )
}

export default Account

