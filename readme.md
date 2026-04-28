# Playto Payout

A merchant payout service with concurrency-safe balance management, idempotent APIs, and background payout processing.

**Stack:** Django + DRF, React + Tailwind, PostgreSQL, Celery + Redis

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- PostgreSQL (running locally)
- Redis (running locally, or via `docker run -d -p 6379:6379 redis:alpine`)

### 1. Clone and setup backend

```bash
git clone <repo-url> && cd playto-payout
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Mac/Linux
pip install -r requirements.txt
```

### 2. Configure environment

```bash
copy .env.example .env       # Windows
# cp .env.example .env       # Mac/Linux
```

Edit `.env` and set your Postgres password in `DATABASE_URL`.

### 3. Create database, migrate, seed

```bash
psql -U postgres -c "CREATE DATABASE playto_payout;"
cd backend
python manage.py migrate
python manage.py seed
```

### 4. Start backend

```bash
cd backend
python manage.py runserver
```

### 5. Start Celery (two terminals)

```bash
cd backend
celery -A config worker --loglevel=info --pool=solo

# In another terminal:
cd backend
celery -A config beat --loglevel=info
```

### 6. Start frontend

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173** — you'll see the merchant dashboard.

## Running Tests

```bash
cd backend
python manage.py test payouts
```

Tests cover:
- **Concurrency** — two simultaneous ₹60 payouts on a ₹100 balance, only one succeeds
- **Idempotency** — duplicate request with same key returns same response, no duplicate payout

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/v1/merchants/` | List merchants |
| GET | `/api/v1/merchants/:id/` | Merchant detail with balance |
| GET | `/api/v1/merchants/:id/ledger/` | Ledger entries |
| GET | `/api/v1/merchants/:id/bank-accounts/` | Bank accounts |
| POST | `/api/v1/merchants/:id/payouts/` | Create payout (requires `Idempotency-Key` header) |
| GET | `/api/v1/merchants/:id/payouts/history/` | Payout history |

## Project Structure

```
backend/
  config/          Django settings, Celery config, URL routing
  payouts/
    models.py      Merchant, BankAccount, LedgerEntry, IdempotencyKey, Payout
    views.py       API endpoints
    serializers.py Request/response serialization
    tasks.py       Celery background workers
    idempotency.py @idempotent decorator
    tests.py       Concurrency + idempotency tests
    management/commands/seed.py

frontend/
  src/
    App.tsx        Dashboard (balance, payout form, history, ledger)
    api.ts         API client
```
