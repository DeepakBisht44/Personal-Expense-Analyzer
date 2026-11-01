# Pennywise — Personal Expense Analyzer

A multi-user personal finance web application based on the submitted PBL proposal. It uses Flask, MySQL, HTML/CSS/JavaScript and Docker Compose.

## Features

- Individual registration, password login and logout; passwords are stored as Werkzeug password hashes, never as plain text.
- Private user-owned transactions, categories, monthly budgets and savings goals. Every read/update/delete query is scoped to the signed-in user, and category IDs are checked for ownership.
- Income/expense transaction create, edit, delete, month/type filtering and description search.
- Dashboard with monthly income, expenses, net balance, savings rate, category breakdown and six-month cash-flow chart.
- Category-based monthly budgets with spending and remaining amount.
- Savings goals with target, saved amount, progress and target date.
- CSRF token checks on JSON write endpoints and logout.
- MySQL data persists in a named Docker volume. Gunicorn serves the Flask app with multiple worker processes and threads.

## Run with Docker (recommended)

1. Install Docker Desktop (Windows/macOS) or Docker Engine + Compose plugin (Linux).
2. Open a terminal in this project directory.
3. Copy `.env.example` to `.env` and change all passwords and `SECRET_KEY` to strong random values.
   - PowerShell: `Copy-Item .env.example .env`
   - macOS/Linux: `cp .env.example .env`
4. Start the application:

   ```bash
   docker compose up --build -d
   ```

5. Open **http://localhost:5000** and register a user account.
6. Share the same reachable host address and port with other users on the same network (for example `http://192.168.1.20:5000`). Each person registers their own account. Do not expose the development deployment directly to the public internet; use HTTPS and a production reverse proxy for public hosting.

Useful commands:

```bash
docker compose ps
docker compose logs -f web
docker compose logs -f db
docker compose down                 # stop containers; keeps database volume
docker compose down -v              # WARNING: deletes the MySQL data volume
```

The web container waits for MySQL's health check, creates the SQLAlchemy tables, and then starts Gunicorn. The MySQL volume is retained across ordinary restarts. Back it up before removing volumes or upgrading the database image.

## Run locally without Docker (optional)

A MySQL 8 server must already be running. Create a database and user, then set environment variables:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

Set `DATABASE_URL` to `mysql+pymysql://USER:PASSWORD@HOST:3306/expense_analyzer` and set `SECRET_KEY`. Initialize and run:

```bash
flask --app app init-db
flask --app app run --host 0.0.0.0 --port 5000
```

For a production deployment, use Gunicorn (the Docker image already does this), HTTPS, a strong secret, backups, and a managed/secured database.

## Multi-user design and privacy

- `users.id` is the owner key for each account.
- `transactions.user_id`, `categories.user_id`, `budgets.user_id` and `savings_goals.user_id` are foreign keys to `users.id`.
- Queries use `current_user.id`; a client cannot access another account's transaction, budget or goal by changing an ID in the URL.
- A category selected for a transaction or budget must belong to the authenticated user.
- Passwords use Werkzeug's adaptive password hashing. Flask-Login protects the application and API routes.
- The database is not published to the host network by Compose. Only the web service port is published.

This is a student project, not a banking product. It does not connect to bank accounts, provide investment advice, or process payments. For real public use, add email verification, password reset, rate limiting, audit logging, stronger operational monitoring, automated backups, HTTPS/reverse proxy and security review.

## Project structure

```text
personal-expense-analyzer/
├── app.py                   # Flask routes, ORM models, auth and analytics
├── requirements.txt
├── Dockerfile
├── docker-compose.yml       # Flask + MySQL + persistent volume
├── .env.example
├── schema.sql               # Relational schema reference
├── templates/
│   ├── base.html
│   ├── auth.html
│   └── dashboard.html
├── static/
│   ├── css/style.css
│   └── js/app.js
├── tests/
└── docs/
    ├── PROJECT_REPORT.md
    └── ARCHITECTURE.md
```

## Main database entities

| Table | Important fields | Purpose |
|---|---|---|
| users | id, name, email, password_hash | Login identity |
| categories | id, user_id, name, kind | Per-user income/expense categories |
| transactions | id, user_id, category_id, kind, amount, transaction_date | Financial records |
| budgets | id, user_id, category_id, month, limit_amount | Monthly category limits |
| savings_goals | id, user_id, title, target_amount, saved_amount, target_date | Savings progress |

## Troubleshooting

- **Port 5000 is busy:** set `APP_PORT=5001` in `.env`, then run `docker compose up -d` and open `http://localhost:5001`.
- **Database is still starting:** `docker compose logs -f db`; the web container waits for its health check.
- **Changed `.env` values:** recreate containers with `docker compose up -d --force-recreate`.
- **Reset all data:** `docker compose down -v` removes the persistent database volume. This is destructive.
