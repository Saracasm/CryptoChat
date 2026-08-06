# Deploying to a free-tier EC2 instance

Everything (Postgres+pgvector, FastAPI backend, Next.js frontend) runs on
one instance via Docker Compose. No RDS, no ALB, no extra paid services --
free-tier EC2 hours are the only AWS cost, and even those are $0 as long as
you stay within the free-tier hour/storage limits (check the exact current
terms on your account -- AWS has changed the free-tier structure for new
signups more than once).

## 1. Launch the instance

- AWS Console -> EC2 -> Launch instance.
- AMI: **Ubuntu Server 22.04 LTS** (or newer LTS).
- Instance type: **t2.micro** or **t3.micro** (whichever your account's
  free tier covers -- check the "Free tier eligible" label in the console).
- Key pair: create a new one, download the `.pem` -- this is your only way
  in, keep it safe.
- Storage: default 8 GB gp3 is enough.
- **Security group** -- add inbound rules for:
  - `22` (SSH) -- source: "My IP" (not 0.0.0.0/0 -- no reason to expose SSH
    to the whole internet)
  - `3000` (frontend) -- source: `0.0.0.0/0`
  - `8000` (backend API, optional -- only if you want to hit `/docs`
    directly) -- source: `0.0.0.0/0`
- Launch, wait for it to reach "running", note the **public IPv4 address**.

## 2. SSH in and install Docker

```bash
ssh -i your-key.pem ubuntu@<public-ip>

curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
newgrp docker   # or log out/in so the group change applies
```

## 3. Get the code onto the box

```bash
git clone <your-repo-url>
cd CryptoChat
cp .env.example .env
nano .env   # fill in POSTGRES_PASSWORD, OPENROUTER_API_KEY, GEMINI_API_KEY
```

Set `ALLOWED_ORIGINS` in `.env` to `http://<public-ip>:3000` once you know
the instance's public IP (needed if you ever call the backend directly from
a browser at that address -- the frontend's own proxy calls don't need it).

## 4. Build and run

```bash
docker compose up -d --build
```

First run pulls `pgvector/pgvector:pg17`, builds the backend and frontend
images, and starts all three. The backend's entrypoint runs
`create_tables.py` on every start (idempotent -- `CREATE ... IF NOT
EXISTS`), so the schema + `vector` extension + HNSW index are ready before
the API starts serving.

Check everything came up:

```bash
docker compose ps
docker compose logs -f backend    # watch for "Application startup complete"
```

## 5. Open it

Visit `http://<public-ip>:3000` in a browser. The Next.js route handlers
proxy server-side to the backend container over the internal Docker
network (`FASTAPI_URL=http://backend:8000`), so the browser never talks to
port 8000 directly -- only port 3000 needs to be reachable for normal use.

## Updating after a code change

```bash
git pull
docker compose up -d --build
```

## Logs / debugging

```bash
docker compose logs -f            # all services
docker compose logs -f backend    # just the API
docker compose exec postgres psql -U cryptochat -d cryptochat
```

## Tearing down

```bash
docker compose down          # stop containers, keep the pgdata volume
docker compose down -v       # stop + delete the Postgres volume too
```

Remember to **stop or terminate the EC2 instance** when you're done for the
day if you're not sure it's fully covered by the free tier -- `docker
compose down` only stops the containers, the instance itself keeps running
(and billing, once free-tier hours are used up) until you stop it in the
EC2 console.
