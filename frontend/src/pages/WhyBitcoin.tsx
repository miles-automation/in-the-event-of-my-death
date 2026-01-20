import { useEffect } from 'react'
import { Link } from 'react-router-dom'

export default function WhyBitcoin() {
  useEffect(() => {
    document.title = 'Why Bitcoin | In The Event Of My Death'
  }, [])

  return (
    <div className="why-bitcoin">
      <h1>Why Bitcoin?</h1>
      <p className="subtitle">How we handle payments without compromising privacy.</p>

      <section className="info-section">
        <h2>No Payment Processor Intermediary</h2>
        <p>
          Traditional payment processors (Stripe, PayPal, Square) require merchant accounts, KYC
          verification, and access to transaction data. With BTCPay Server, payments go directly
          from you to us with no third party in between.
        </p>
      </section>

      <section className="info-section">
        <h2>Privacy Alignment</h2>
        <p>
          IEOMD is built on zero-knowledge principles: we cannot read your secrets, and we
          don&apos;t track who creates them. Using a self-hosted payment processor means payment
          data stays consistent with this model.
        </p>
        <p>We collect the minimum data needed to process a payment:</p>
        <ul>
          <li>Payment amount and confirmation</li>
          <li>A capability token tied to your secret (not your identity)</li>
        </ul>
        <p>We do not collect:</p>
        <ul>
          <li>Names, emails, or addresses</li>
          <li>IP addresses or browser fingerprints</li>
          <li>Purchase history or usage patterns</li>
        </ul>
      </section>

      <section className="info-section">
        <h2>Simple One-Time Payments</h2>
        <p>
          Premium is a one-time $1 payment, not a subscription. Bitcoin&apos;s transaction model is
          well-suited for this: pay once, receive a capability token, done. No recurring billing, no
          payment method on file, no renewal notices.
        </p>
      </section>

      <section className="info-section">
        <h2>Self-Hosted Infrastructure</h2>
        <p>
          Our payment processor runs on infrastructure we control at <code>pay.sparkswarm.com</code>
          . BTCPay Server is open-source software that we deploy and maintain ourselves. This means:
        </p>
        <ul>
          <li>No external service has access to transaction data</li>
          <li>We control uptime and availability</li>
          <li>No vendor lock-in or platform risk</li>
        </ul>
      </section>

      <section className="info-section">
        <h2>What About Other Cryptocurrencies?</h2>
        <p>
          BTCPay Server supports Bitcoin and Lightning Network. We may add additional payment
          methods in the future based on user demand, but our priority is keeping the payment
          experience simple and reliable.
        </p>
      </section>

      <p className="back-link">
        <Link to="/pricing">Back to Pricing</Link>
      </p>
    </div>
  )
}
