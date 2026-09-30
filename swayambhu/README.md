# SWAYAMBHU 2026 · AI QR QUEST

Admin-controlled event operations for a three-round QR treasure hunt. There is no public team registration or payment flow. Teams are created by event staff, and participants sign in with their assigned Team ID and PIN.

## PostgreSQL setup on Windows

```powershell
cd swayambhu
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Open a PostgreSQL prompt as the `postgres` user and create the database. Set or change the password interactively so it is not written into shell history:

```powershell
psql -U postgres -h localhost
```

At the `psql` prompt:

```sql
CREATE DATABASE swayambhu_db;
\password postgres
\q
```

Create the ignored local environment file and replace `YOUR_PASSWORD` with that PostgreSQL password. Also replace the `SECRET_KEY` value with a private random value of at least 32 characters:

```powershell
Copy-Item .env.example .env
```

The expected database URL is `postgresql://postgres:YOUR_PASSWORD@localhost:5432/swayambhu_db`. The application loads `.env` and selects the `psycopg2` driver; no database password is stored in Python.

## Initialize and run

```powershell
flask --app app db upgrade
flask --app app init-db
flask --app app create-admin
python app.py
```

Visit `http://127.0.0.1:5000/health/db` to verify connectivity. A successful PostgreSQL check returns `{"database":"postgresql","status":"ok"}`. The `init-db` command seeds Round 1 (QR Riddle), Round 2 (Quiz Challenge), and Round 3 (Pen & Paper Final Challenge); migration/initialization can safely be repeated.

## Admin credentials

There is no preset admin username or password. Create the administrator before signing in:

```powershell
flask --app app create-admin
```

At the prompts, enter the username you want to use and a private password of at least 12 characters. The password is entered twice and stored as a hash. Teams use the Team ID and PIN assigned by an administrator at `/team/login`.

Create future migrations with `flask --app app db migrate -m "describe change"`, review the generated revision, then apply it with `flask --app app db upgrade`. Set `APP_ENV=production` and `COOKIE_SECURE=true` when served behind HTTPS. Serve through a production WSGI/Socket.IO deployment; do not use Flask's development server for public traffic.

## Tests

```powershell
python -m unittest discover -s tests -v
```

The tests use an isolated in-memory SQLite database. Browser camera scanning requires HTTPS except on localhost and permission to use the camera. A manual token field is available as a fallback.

## Event workflow

1. Sign in as an administrator and create teams. The generated Team ID and PIN are shown once; share them with each team.
2. Add Round 1 clues and Round 2 MCQs. Generate QR codes and download the PNGs, then activate the relevant codes.
3. Unlock/start rounds from Round Control. Teams start their own server-timed round session before scanning or taking the quiz.
4. Enter Round 3 judge scores in Scores. End each event round when operations are complete.
5. Generate final results after all three rounds have ended, then lock them. Only a super-admin can unlock results.

All key scoring and timestamps are recorded server-side. QR images contain opaque random tokens, never answers. Admin activity is delivered in real time over Socket.IO to authenticated admin sockets; leaderboard updates are shared with signed-in teams.