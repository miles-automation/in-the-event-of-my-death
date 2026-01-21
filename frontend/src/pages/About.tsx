import { useEffect } from 'react'

export default function About() {
  useEffect(() => {
    document.title = 'About | In The Event Of My Death'
  }, [])

  return (
    <div className="about">
      <h1>About</h1>
      <p className="subtitle">How we keep your secrets safe.</p>

      <section id="how-it-works" className="info-section">
        <h2>How It Works</h2>
        <ol>
          <li>Write your secret message</li>
          <li>
            Choose an unlock date (when it becomes accessible) and expiry date (when it&apos;s
            deleted)
          </li>
          <li>Share the view link with your recipient</li>
          <li>Keep the edit link to adjust dates if needed</li>
        </ol>
      </section>

      <section id="security-privacy" className="info-section">
        <h2>Security &amp; Privacy</h2>
        <ul>
          <li>
            <strong>Zero Knowledge:</strong> End-to-end encrypted. We never see your content or
            keys.
          </li>
          <li>
            <strong>Time-Locked:</strong> Recipients can only access after the unlock date.
          </li>
          <li>
            <strong>One-Time Access:</strong> Retrieved once, then encrypted content permanently
            cleared.
          </li>
          <li>
            <strong>No Accounts:</strong> No sign-up. Just create and share.
          </li>
        </ul>
      </section>

      <section id="analytics" className="info-section">
        <h2>Analytics</h2>
        <p>
          We use <a href="https://umami.is">Umami</a>, a privacy-focused analytics service we host
          ourselves at analytics.sparkswarm.com. Umami does not use cookies, does not track
          individuals across sites, and does not collect personal information. We only see aggregate
          page views and browser statistics to understand how people use IEOMD.
        </p>
      </section>

      <section id="faq" className="info-section">
        <h2>FAQ</h2>
        <div className="faq-item">
          <h3>Can you read my messages?</h3>
          <p>
            No. Your messages are encrypted in your browser before they reach our servers. The
            encryption key is stored only in the URL fragment (the part after the #), which is never
            sent to the server. This means we have no way to decrypt your data.
          </p>
        </div>
        <div className="faq-item">
          <h3>What happens if I lose the link?</h3>
          <p>
            Unfortunately, the link cannot be recovered. Since the encryption key is stored only in
            the URL, losing the link means the secret is permanently inaccessible. We recommend
            saving both the view link and edit link in a secure location.
          </p>
        </div>
        <div className="faq-item">
          <h3>What&apos;s the difference between unlock date and expiry date?</h3>
          <p>
            The <strong>unlock date</strong> is when your recipient can first access the secret. The{' '}
            <strong>expiry date</strong> is when the secret is permanently cleared, whether
            retrieved or not. You can set unlock dates up to 2 years and expiry dates up to 5 years
            in the future. Use the edit link to adjust either date before the secret unlocks.
          </p>
        </div>
        <div className="faq-item">
          <h3>What if I don&apos;t retrieve my secret before it expires?</h3>
          <p>
            If a secret is not retrieved before its expiry date, its encrypted content is
            permanently cleared from our servers and cannot be recovered. Make sure the expiry date
            gives your recipient enough time after the unlock date to retrieve the secret.
          </p>
        </div>
      </section>

      <section id="encryption" className="info-section">
        <h2>Technical Details</h2>
        <p>
          Your secrets are encrypted using AES-256-GCM in your browser before being sent to our
          servers. The encryption key is stored only in the URL fragment, which is never sent to the
          server. This means we can never decrypt your data—only someone with the complete link can
          access it.
        </p>
      </section>
    </div>
  )
}
