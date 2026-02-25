import React from 'react'
import './WarningModal.css'

const WarningModal = ({ isOpen, onClose, title, message, devices }) => {
    if (!isOpen) return null

    return (
        <div className="warning-modal-overlay" onClick={onClose}>
            <div className="warning-modal-content" onClick={e => e.stopPropagation()}>
                <div className="warning-modal-header">
                    <h2>{title || 'Warning'}</h2>
                    <button className="warning-modal-close" onClick={onClose}>&times;</button>
                </div>
                <div className="warning-modal-body">
                    <p>{message}</p>
                    {devices && devices.length > 0 && (
                        <div className="warning-modal-devices">
                            {devices.map((device, idx) => (
                                <div key={idx} className="warning-modal-device">
                                    <strong>{device.token_name}</strong>
                                    <span>Version: {device.client_version}</span>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
                <div className="warning-modal-footer">
                    <button className="warning-modal-btn" onClick={onClose}>Close</button>
                </div>
            </div>
        </div>
    )
}

export default WarningModal
