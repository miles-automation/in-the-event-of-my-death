import { useEffect } from 'react'
import { Link } from 'react-router-dom'

export default function Pricing() {
  useEffect(() => {
    document.title = 'Pricing | In The Event Of My Death'
  }, [])

  return (
    <div className="pricing">
      <h1>Pricing</h1>
      <p className="subtitle">Simple, one-time payments. No subscriptions.</p>

      <div className="pricing-tiers">
        <div className="tier tier-free">
          <h2>Free</h2>
          <p className="tier-price">$0</p>
          <ul className="tier-features">
            <li>Up to 10MB file attachments</li>
            <li>365-day maximum expiry</li>
            <li>End-to-end encryption</li>
            <li>No account required</li>
          </ul>
          <Link to="/" className="button secondary">
            Create a Secret
          </Link>
        </div>

        <div className="tier tier-premium">
          <h2>Premium</h2>
          <p className="tier-price">$1</p>
          <p className="tier-price-note">one-time payment</p>
          <ul className="tier-features">
            <li>Up to 500MB file attachments</li>
            <li>5-year maximum expiry</li>
            <li>End-to-end encryption</li>
            <li>No account required</li>
          </ul>
          <button className="button primary" disabled>
            Coming Soon
          </button>
        </div>
      </div>

      <section className="info-section">
        <h2>What Premium Does Not Include</h2>
        <p>
          IEOMD is intentionally minimal. Premium unlocks larger limits, not features. To preserve
          privacy, we do not offer:
        </p>
        <ul>
          <li>
            <strong>User accounts:</strong> No sign-up, no password, no profile.
          </li>
          <li>
            <strong>Dashboards or analytics:</strong> We don&apos;t track your secrets or usage.
          </li>
          <li>
            <strong>Usage history:</strong> Once created, secrets exist only via their links.
          </li>
          <li>
            <strong>Content recovery:</strong> Lost link = lost secret. We cannot help recover it.
          </li>
        </ul>
      </section>

      <section className="info-section">
        <h2>Why Bitcoin?</h2>
        <p>
          We accept Bitcoin payments through BTCPay Server, a self-hosted payment processor. This
          aligns with IEOMD&apos;s privacy-first approach.
        </p>
        <p>
          <Link to="/why-bitcoin">Learn more about our payment infrastructure</Link>
        </p>
      </section>
    </div>
  )
}
