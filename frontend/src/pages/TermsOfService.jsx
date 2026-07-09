import React from 'react'
import { Link } from 'react-router-dom'
import './LegalPage.css'

const TermsOfService = () => {
  return (
    <div className="legal-page">
      <div className="legal-container">
        <h1>Terms of Service</h1>
        <p className="legal-updated">Last updated: July 4, 2026</p>

        <p>
          These Terms of Service ("Terms") govern your access to and use of the
          Team Pixel Nostalgia application, website, and related services (the
          "Service"). By accessing or using the Service, you agree to be bound
          by these Terms. If you do not agree, do not use the Service.
        </p>

        <h2>1. Eligibility and Access</h2>
        <p>
          Access to the Service requires authentication through Discord and
          membership in the Team Pixel Nostalgia Discord server. We reserve the
          right to grant, restrict, or revoke access to any user at any time,
          at our sole discretion, without notice.
        </p>

        <h2>2. Acceptable Use</h2>
        <p>When using the Service, you agree not to:</p>
        <ul>
          <li>Use the Service for any unlawful purpose or in violation of any applicable laws;</li>
          <li>Attempt to gain unauthorized access to the Service, other users' accounts, or restricted areas;</li>
          <li>Interfere with, disrupt, or place undue load on the Service or its infrastructure;</li>
          <li>Share your account or authentication credentials with others;</li>
          <li>Scrape, harvest, or redistribute content from the Service without permission.</li>
        </ul>

        <h2>3. User Contributions</h2>
        <p>
          The Service may allow you to submit content such as media, metadata,
          or bug reports. By submitting content, you grant us a non-exclusive,
          royalty-free license to use, host, display, and distribute that
          content within the Service. You are responsible for ensuring that any
          content you submit does not infringe the rights of third parties. We
          may review, moderate, or remove submitted content at any time.
        </p>

        <h2>4. Intellectual Property</h2>
        <p>
          All trademarks, logos, and content provided through the Service
          belong to their respective owners. Nothing in these Terms grants you
          any right to use our name, logo, or branding without prior written
          consent.
        </p>

        <h2>5. Third-Party Services</h2>
        <p>
          The Service relies on third-party services, including Discord, for
          authentication and community features. Your use of those services is
          governed by their own terms and policies, which we encourage you to
          review.
        </p>

        <h2>6. Disclaimer of Warranties</h2>
        <p>
          The Service is provided "as is" and "as available" without warranties
          of any kind, whether express or implied. We do not guarantee that the
          Service will be uninterrupted, error-free, or secure.
        </p>

        <h2>7. Limitation of Liability</h2>
        <p>
          To the maximum extent permitted by law, we shall not be liable for
          any indirect, incidental, special, consequential, or punitive
          damages, or any loss of data, arising out of or related to your use
          of the Service.
        </p>

        <h2>8. Termination</h2>
        <p>
          We may suspend or terminate your access to the Service at any time,
          for any reason, including violation of these Terms. Upon termination,
          your right to use the Service ceases immediately.
        </p>

        <h2>9. Changes to These Terms</h2>
        <p>
          We may update these Terms from time to time. Continued use of the
          Service after changes take effect constitutes acceptance of the
          revised Terms. The "Last updated" date at the top of this page
          indicates when these Terms were last revised.
        </p>

        <h2>10. Contact</h2>
        <p>
          If you have questions about these Terms, please contact us through
          the Team Pixel Nostalgia Discord server.
        </p>

        <div className="legal-footer">
          <Link to="/">Go to Home</Link>
          <Link to="/privacy-policy" className="secondary">Privacy Policy</Link>
        </div>
      </div>
    </div>
  )
}

export default TermsOfService
