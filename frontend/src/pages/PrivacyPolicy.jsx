import React from 'react'
import { Link } from 'react-router-dom'
import './LegalPage.css'

const PrivacyPolicy = () => {
  return (
    <div className="legal-page">
      <div className="legal-container">
        <h1>Privacy Policy</h1>
        <p className="legal-updated">Last updated: July 4, 2026</p>

        <p>
          This Privacy Policy describes how the Team Pixel Nostalgia
          application (the "Service") collects, uses, and protects your
          information when you use the Service.
        </p>

        <h2>1. Information We Collect</h2>
        <p>
          When you sign in with Discord, we receive and store the following
          information from your Discord account:
        </p>
        <ul>
          <li>Your Discord user ID, username, and avatar;</li>
          <li>Your membership and roles in the Team Pixel Nostalgia Discord server, used to determine your access permissions.</li>
        </ul>
        <p>While you use the Service, we may also collect:</p>
        <ul>
          <li>Usage data such as download history, connected devices, and activity statistics;</li>
          <li>Content you voluntarily submit, such as media contributions or bug reports;</li>
          <li>Technical data such as session information required to keep you signed in.</li>
        </ul>
        <p>
          We do not collect your Discord email address, password, or private
          messages, and we do not collect payment information.
        </p>

        <h2>2. How We Use Your Information</h2>
        <p>We use the information we collect to:</p>
        <ul>
          <li>Authenticate you and manage your access to the Service;</li>
          <li>Provide core features such as downloads, device management, and contributions;</li>
          <li>Maintain usage statistics and improve the Service;</li>
          <li>Moderate content and enforce our Terms of Service.</li>
        </ul>

        <h2>3. Cookies and Sessions</h2>
        <p>
          The Service uses cookies or similar technologies strictly to maintain
          your authenticated session. We do not use cookies for advertising or
          cross-site tracking.
        </p>

        <h2>4. Sharing of Information</h2>
        <p>
          We do not sell, rent, or trade your personal information. Your
          information is not shared with third parties, except when required by
          law or necessary to operate the Service (for example, authentication
          through Discord, which is governed by Discord's own privacy policy).
        </p>

        <h2>5. Data Retention</h2>
        <p>
          We retain your information for as long as your account is active or
          as needed to provide the Service. Usage statistics may be retained in
          aggregated form. You may request deletion of your data at any time by
          contacting us through the Team Pixel Nostalgia Discord server.
        </p>

        <h2>6. Data Security</h2>
        <p>
          We take reasonable technical and organizational measures to protect
          your information from unauthorized access, loss, or misuse. However,
          no method of transmission or storage is completely secure, and we
          cannot guarantee absolute security.
        </p>

        <h2>7. Your Rights</h2>
        <p>
          Depending on your jurisdiction, you may have the right to access,
          correct, or delete your personal information. To exercise these
          rights, contact us through the Team Pixel Nostalgia Discord server.
        </p>

        <h2>8. Children's Privacy</h2>
        <p>
          The Service is not directed at children under the age of 13 (or the
          minimum age required by Discord in your country). We do not knowingly
          collect personal information from children.
        </p>

        <h2>9. Changes to This Policy</h2>
        <p>
          We may update this Privacy Policy from time to time. The "Last
          updated" date at the top of this page indicates when it was last
          revised. Continued use of the Service after changes take effect
          constitutes acceptance of the updated policy.
        </p>

        <h2>10. Contact</h2>
        <p>
          If you have questions about this Privacy Policy or your data, please
          contact us through the Team Pixel Nostalgia Discord server.
        </p>

        <div className="legal-footer">
          <Link to="/">Go to Home</Link>
          <Link to="/terms-of-service" className="secondary">Terms of Service</Link>
        </div>
      </div>
    </div>
  )
}

export default PrivacyPolicy
