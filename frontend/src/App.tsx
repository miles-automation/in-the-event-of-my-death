import { BrowserRouter, Routes, Route, Link } from 'react-router-dom'
import Home from './pages/Home'
import ViewSecret from './pages/ViewSecret'
import EditSecret from './pages/EditSecret'
import About from './pages/About'
import Feedback from './pages/Feedback'
import Pricing from './pages/Pricing'
import WhyBitcoin from './pages/WhyBitcoin'
import PrivacyPolicy from './pages/PrivacyPolicy'
import TermsOfService from './pages/TermsOfService'
import './App.css'

function App() {
  return (
    <BrowserRouter>
      <div className="app">
        <div className="beta-badge" role="status" aria-label="Beta version">
          BETA
        </div>
        <main>
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/view" element={<ViewSecret />} />
            <Route path="/edit" element={<EditSecret />} />
            <Route path="/about" element={<About />} />
            <Route path="/feedback" element={<Feedback />} />
            <Route path="/pricing" element={<Pricing />} />
            <Route path="/why-bitcoin" element={<WhyBitcoin />} />
            <Route path="/privacy" element={<PrivacyPolicy />} />
            <Route path="/terms" element={<TermsOfService />} />
          </Routes>
        </main>

        <footer className="site-footer">
          <div className="footer-content">
            <p className="footer-line">
              <Link to="/about">About</Link>
              <span className="footer-separator">•</span>
              <Link to="/pricing">Pricing</Link>
              <span className="footer-separator">•</span>
              <Link to="/feedback">Feedback</Link>
              <span className="footer-separator">•</span>
              <Link to="/privacy">Privacy</Link>
              <span className="footer-separator">•</span>
              <Link to="/terms">Terms</Link>
            </p>
            <p className="footer-version">v{__APP_VERSION__}</p>
          </div>
        </footer>
      </div>
    </BrowserRouter>
  )
}

export default App
