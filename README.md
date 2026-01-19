# InTheEventOfMyDeath.com

A privacy-preserving, zero-knowledge time-locked secret delivery service. This service allows users to create encrypted messages or files with configurable unlock and expiry times, distribute a decryption link to recipients, and retain an edit link to postpone the unlock or expiry dates.

## Overview

InTheEventOfMyDeath.com enables you to:
- **Create time-locked secrets**: Submit text or files that will be released after a specific date/time
- **Maintain zero-knowledge privacy**: The server stores only encrypted data, never plaintext or decryption keys
- **Control access**: Two distinct links are generated:
  - An **edit link** for the author to postpone the unlock or expiration dates (before unlock)
  - A **decrypt link** for recipients to retrieve and decrypt the message after unlock

## Features

- **Client-side encryption**: All encryption/decryption happens in your browser using AES-256-GCM
- **Time-locked delivery**: Server enforces unlock date and never serves ciphertext before the scheduled time
- **One-time access**: Ciphertext is cleared after first successful post-unlock retrieval (metadata retained)
- **Abuse prevention**: Proof-of-work challenges prevent spam and automated attacks
- **Anonymous usage**: No accounts required, minimal metadata collection
- **Zero-knowledge storage**: Server never has access to your decryption keys or plaintext data

## Architecture

The application consists of three main components:

### Backend (FastAPI + SQLAlchemy)
- RESTful API for secret management
- Time-based access control enforcement
- Proof-of-work challenge generation and verification
- Encrypted secret storage with SQLAlchemy (database-agnostic)
- Located in `/backend`

### Frontend (React + TypeScript + Vite)
- Modern, responsive UI
- Client-side encryption/decryption using Web Crypto API
- Real-time expiry countdown
- Located in `/frontend`

### Database
- SQLite for local development (configured via DATABASE_URL)
- SQLAlchemy ORM supports various production databases
- Stores only encrypted ciphertext and minimal metadata
- Automated clearing of ciphertext for expired or retrieved secrets (metadata retained)

## Local Setup

### Prerequisites

- **Python 3.11+** with [Poetry](https://python-poetry.org/)
- **Node.js 18+** with npm
- **Make** (optional, for convenience commands)

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/richmiles/in-the-event-of-my-death.git
   cd in-the-event-of-my-death
   ```

2. **Install dependencies:**
   ```bash
   make install
   ```

   Or manually:
   ```bash
   # Backend
   cd backend
   poetry install

   # Frontend
   cd frontend
   npm install
   ```

3. **Copy environment files:**
   ```bash
   cp frontend/.env.example frontend/.env
   cp backend/.env.example backend/.env
   ```

4. **Run database migrations:**
   ```bash
   make migrate
   ```

   Or manually:
   ```bash
   cd backend
   poetry run alembic upgrade head
   ```

### Running the Application

**Option 1: Use Make (runs both backend and frontend)**
```bash
make dev
```

**Option 2: Run individually**

Backend (starts on http://localhost:8000):
```bash
make backend
```

Frontend (starts on http://localhost:5173):
```bash
make frontend
```

The frontend calls the backend API at `${VITE_API_URL}/api/v1` (in production it defaults to same-origin `/api/v1`).

### Development Commands

```bash
make help          # Show all available commands
make test          # Run all tests (backend + frontend)
make lint          # Run linters for both backend and frontend
make format        # Auto-format code
make typecheck     # Run TypeScript type checking
make check         # Run lint, typecheck, and tests
```

## Configuration

### Frontend Configuration

Create a `.env` file in the `frontend/` directory based on `.env.example`:

```env
# API Configuration
VITE_API_URL=http://localhost:8000

# Base URL for shareable links
# In production, set this to your domain (e.g., https://ieomd.com)
VITE_BASE_URL=http://localhost:5173
```

**Variables:**
- `VITE_API_URL`: Optional backend server URL (origin). The frontend calls `${VITE_API_URL}/api/v1/...`. If unset in production, it defaults to same-origin `/api/v1`.
- `VITE_BASE_URL`: Base URL used for generating shareable links. In production, this should be set to your production domain

### Backend Configuration

Create a `.env` file in the `backend/` directory based on `.env.example`:

```env
# Database Configuration
DATABASE_URL=sqlite:///./secrets.db

# CORS Configuration
# Comma-separated list of allowed origins
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173

# Proof of Work
# Base difficulty; the service auto-adjusts per payload size
POW_BASE_DIFFICULTY=18
POW_CHALLENGE_TTL_SECONDS=300

# Rate Limiting (per slowapi syntax)
RATE_LIMIT_CHALLENGES=10/minute
RATE_LIMIT_CREATES=5/minute
RATE_LIMIT_RETRIEVES=30/minute
```

**Variables:**
- `DATABASE_URL`: Database connection string. Default is SQLite for development. For production, consider PostgreSQL
- `CORS_ORIGINS`: Comma-separated list of allowed CORS origins. In production, set this to your frontend URL
- `POW_BASE_DIFFICULTY`: Proof-of-work difficulty baseline; the service increases difficulty for larger payloads
- `POW_CHALLENGE_TTL_SECONDS`: How long proof-of-work challenges remain valid
- `RATE_LIMIT_CHALLENGES`: Rate limit for requesting proof-of-work challenges
- `RATE_LIMIT_CREATES`: Rate limit for creating secrets
- `RATE_LIMIT_RETRIEVES`: Rate limit for retrieving secrets

⚠️ **Never commit `.env` files or secrets to the repository!**

## Project Structure

```
.
├── backend/              # FastAPI backend application
│   ├── alembic/         # Database migrations
│   ├── app/
│   │   ├── models/      # SQLAlchemy models
│   │   ├── routers/     # API route handlers
│   │   ├── schemas/     # Pydantic schemas
│   │   └── services/    # Business logic
│   ├── tests/           # Backend tests
│   └── pyproject.toml   # Python dependencies
├── frontend/            # React frontend application
│   ├── src/
│   │   ├── components/  # React components
│   │   ├── hooks/       # Custom React hooks
│   │   ├── pages/       # Page components
│   │   ├── services/    # API and crypto services
│   │   ├── types/       # TypeScript types
│   │   ├── utils/       # Utility functions
│   │   └── workers/     # Web workers (PoW)
│   ├── public/          # Static assets
│   └── package.json     # Node dependencies
├── docs/                # Additional documentation
│   └── design.md        # System design document
├── .gitignore           # Git ignore rules
├── CONTRIBUTING.md      # Contribution guidelines
├── LICENSE              # MIT License
├── Makefile             # Development commands
├── README.md            # This file
└── SECURITY.md          # Security policy
```

## Deployment

Production runs on shared infrastructure managed by [platform-infra](https://github.com/richmiles/platform-infra). See [docs/deploy.md](docs/deploy.md) for deployment instructions.

For release/versioning and database migration policy, see [docs/versioning-and-migrations.md](docs/versioning-and-migrations.md).

## Security

This project implements several security measures:

- **Client-side encryption**: All sensitive data is encrypted in the browser before transmission using AES-256-GCM
- **Zero-knowledge architecture**: Server never has access to plaintext or decryption keys. Encryption keys are only included in URL fragments (which are not transmitted to the server per RFC 3986)
- **Proof-of-work**: Prevents automated abuse and spam
- **Rate limiting**: Protects against DoS attacks
- **HTTPS-only**: All communications encrypted in transit
- **Minimal retention**: Ciphertext cleared after retrieval or expiry; metadata retained for analytics

For more details, see [docs/design.md](docs/design.md) and [SECURITY.md](SECURITY.md).

## Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on:
- Reporting bugs and proposing features
- Development setup and coding standards
- Pull request requirements

## Testing

```bash
make test    # Run backend tests
make check   # Run all checks (lint, format, typecheck, test)
```

Staging/production smoke tests are documented in `docs/smoke-tests.md`.

See [CONTRIBUTING.md](CONTRIBUTING.md) for testing requirements when submitting PRs.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- Built with [FastAPI](https://fastapi.tiangolo.com/), [React](https://react.dev/), and [TypeScript](https://www.typescriptlang.org/)
- Cryptography powered by the [Web Crypto API](https://developer.mozilla.org/en-US/docs/Web/API/Web_Crypto_API)
- Inspired by the need for privacy-preserving communication tools

## Support

For questions and support, please open an issue on GitHub.
