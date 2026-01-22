import { useEffect } from 'react'

export default function PrivacyPolicy() {
  useEffect(() => {
    document.title = 'Privacy Policy | In The Event Of My Death'
  }, [])

  return (
    <div className="about">
      <h1>Privacy Policy</h1>
      <p className="subtitle">How we protect your privacy.</p>

      <section className="info-section">
        <h2>Zero-Knowledge Architecture</h2>
        <p>
          This service is built with privacy at its core. We use a zero-knowledge architecture,
          which means we <strong>cannot</strong> read your secrets—even if we wanted to.
        </p>
        <p>
          All encryption and decryption happens entirely in your browser. The encryption key is
          stored only in the URL fragment (the part after the #), which is never sent to our
          servers. This means your secret remains private between you and whoever has the complete
          link.
        </p>
      </section>

      <section className="info-section">
        <h2>What We Store</h2>
        <ul>
          <li>
            <strong>Encrypted data:</strong> Your secret is encrypted in your browser using
            AES-256-GCM before being sent to our servers. We only store the encrypted blob—we have
            no way to decrypt it.
          </li>
          <li>
            <strong>Timestamps:</strong> We store the unlock date (when the secret becomes
            accessible) and expiry date (when the secret is permanently deleted).
          </li>
          <li>
            <strong>Access tokens:</strong> We generate random tokens to control access to your
            secret (for viewing and editing). These tokens are included in the links you share.
          </li>
          <li>
            <strong>Metadata:</strong> We may collect minimal metadata such as creation timestamps
            and access logs for security and analytics purposes.
          </li>
        </ul>
      </section>

      <section className="info-section">
        <h2>What We Don&apos;t Store</h2>
        <ul>
          <li>
            <strong>Encryption keys:</strong> The key to decrypt your secret never leaves your
            browser and is never sent to our servers.
          </li>
          <li>
            <strong>Plaintext content:</strong> We never have access to the unencrypted content of
            your secrets.
          </li>
          <li>
            <strong>Personal information:</strong> We don&apos;t require accounts, emails, or any
            personal information to use this service.
          </li>
        </ul>
      </section>

      <section className="info-section">
        <h2>Analytics</h2>
        <p>
          We use{' '}
          <a href="https://umami.is" target="_blank" rel="noopener noreferrer">
            Umami
          </a>
          , a privacy-focused, open-source analytics platform. Umami does not use cookies, does not
          track users across websites, and does not collect personal information. All data is
          aggregated and anonymized. We use analytics solely to understand how the service is used
          and to improve it.
        </p>
        <p>
          We do not sell any data to third parties. Analytics data is hosted on our own
          infrastructure at analytics.sparkswarm.com.
        </p>
      </section>

      <section className="info-section">
        <h2>Payments</h2>
        <p>
          Premium features are paid for using Bitcoin via{' '}
          <a href="https://btcpayserver.org" target="_blank" rel="noopener noreferrer">
            BTCPay Server
          </a>
          , a self-hosted, open-source payment processor. We do not collect credit card information
          or require personal details to purchase premium features.
        </p>
        <ul>
          <li>
            <strong>Payment processor:</strong> BTCPay Server, self-hosted at pay.sparkswarm.com
          </li>
          <li>
            <strong>What we store:</strong> Invoice IDs and capability tokens linking payments to
            premium features. We do not store Bitcoin addresses or transaction details beyond what
            is needed to verify payment completion.
          </li>
          <li>
            <strong>Capability tokens:</strong> After payment, you receive a one-time-use token that
            grants premium features. This token is not linked to any personal information.
          </li>
        </ul>
      </section>

      <section className="info-section">
        <h2>Data Retention</h2>
        <ul>
          <li>
            <strong>Automatic clearing:</strong> The encrypted content of secrets is automatically
            cleared after their expiry date, whether they were retrieved or not.
          </li>
          <li>
            <strong>One-time access:</strong> Once a secret is successfully retrieved after its
            unlock date, its encrypted content (ciphertext, initialization vector, and
            authentication tag) is immediately cleared from our servers.
          </li>
          <li>
            <strong>Metadata retention:</strong> After encrypted content is cleared, we retain
            minimal metadata (timestamps, access tokens) for security and analytics purposes. This
            metadata cannot be used to recover the secret&apos;s content.
          </li>
        </ul>
      </section>

      <section className="info-section">
        <h2>Security</h2>
        <p>
          We take security seriously. Our infrastructure uses industry-standard security practices
          to protect the encrypted data we store. However, since we use zero-knowledge encryption,
          even if our servers were compromised, your secrets would remain protected as long as you
          keep your links private.
        </p>
        <p>
          <strong>Your responsibility:</strong> The security of your secret depends on keeping the
          view and edit links private. Anyone with the complete link can access your secret once
          it&apos;s unlocked. Treat these links like passwords.
        </p>
      </section>

      <section className="info-section">
        <h2>Changes to This Policy</h2>
        <p>
          We may update this privacy policy from time to time. If we make significant changes, we
          will notify users through the service. Continued use of the service after changes
          constitutes acceptance of the updated policy.
        </p>
      </section>

      <section className="info-section">
        <h2>Contact</h2>
        <p>
          If you have questions about this privacy policy or how we handle your data, please contact
          us through our GitHub repository:{' '}
          <a
            href="https://github.com/richmiles/in-the-event-of-my-death"
            target="_blank"
            rel="noopener noreferrer"
          >
            github.com/richmiles/in-the-event-of-my-death
          </a>
        </p>
      </section>
    </div>
  )
}
