# Bid System

A high-concurrency online bidding system. This is the final project for **Practices for Distributed Systems and Cloud Application Development** (NTU, 2025 Fall), reorganized and republished after the course.

An admin lists a product with a limited quantity `K` and a bidding window. Users place bids, and when the window ends the top `K` bidders by score win. Bids are served from Redis for speed, and PostgreSQL stores the permanent records.

## Architecture

```
Browser (frontend/*.html)
        |
   Load balancer  (AWS ALB + Auto Scaling in the original deployment)
        |
 FastAPI backend (Docker)
     |         |
 Redis/Valkey  PostgreSQL
 (live bids)   (members, products, winners)
```

* **FastAPI + `databases`/SQLAlchemy** for the API and PostgreSQL access.
* **Redis (Valkey)** holds the live ranking (sorted set), bid details (hash), and caches the current product and each user's weight, so the bid path never touches SQL.
* **PostgreSQL** (AWS RDS in the original deployment) stores members, products and winners.
* **Lazy settlement**: the first `get_product` call after the bidding window ends settles the product inside a transaction with a row lock (`SELECT ... FOR UPDATE`), so concurrent requests settle it only once.

## Scoring

```
score = alpha * P + beta / (T + 1) + gamma * W
```

* `P`: bid price
* `T`: milliseconds since the product opened (earlier bids score higher)
* `W`: user weight, equal to the number of auctions the user has won
* `alpha`, `beta`, `gamma`: set per product by the admin (defaults `3.0`, `5.0`, `3.0`)

## Project Structure

```
main.py             App entry point, lifespan, CORS, router registration
database.py         PostgreSQL tables and Redis client (reads DATABASE_URL / REDIS_URL)
routers/
  bidding.py        Bid, ranking, product, settlement and reset endpoints
  admin.py          List a product, set score weights
  users.py          Register / login
frontend/           Static pages: login.html, user.html, admin.html
Dockerfile, docker-compose.yml, .env.example
```

## Getting Started

1. Provide a PostgreSQL and a Redis instance, then copy the example environment file and fill it in:

   ```bash
   cp .env.example .env
   ```

   `.env` is git-ignored. When no environment variables are set, `database.py` falls back to `postgresql://postgres:postgres@localhost:5432/bid_system` and `redis://localhost:6379/0`.

2. Create the tables (once):

   ```bash
   pip install -r requirements.txt
   python database.py
   ```

3. Run the backend:

   ```bash
   docker compose up --build
   # or, without Docker:
   uvicorn main:app --host 0.0.0.0 --port 8000
   ```

   Interactive API docs are at `http://localhost:8000/docs`.

4. Open `frontend/login.html` in a browser. Each page has a `backend` constant at the top of its script, which defaults to `http://localhost:8000`; point it at your backend or load balancer URL if needed.

## API Overview

| Method | Path | Description |
| --- | --- | --- |
| POST | `/user/register` | Register a user |
| POST | `/user/login` | Log in and get the user's weight |
| POST | `/admin/set_product` | List a new product (name, base price, quantity, duration) |
| POST | `/admin/set_score` | Set `alpha` / `beta` / `gamma` for the latest product |
| POST | `/api/bid` | Place a bid |
| GET | `/api/get_product` | Current product, live bids and winners (triggers settlement when due) |
| GET | `/api/bid_list` | Current top-K ranking |
| GET | `/api/get_bid_price` | A user's current bid and score |
| GET | `/api/user_info` | A user's weight |
| POST | `/api/reset_all_data` | Demo only: wipes Redis and all tables |

## Load Test Results

Load-tested against the AWS deployment (ALB + Auto Scaling Group + RDS + ElastiCache/Valkey) with Locust. Full course presentation (Chinese): `docs/Group7.pdf`.

**Setup**

* Auto Scaling Group: starts at 1 instance, max 3; scale-out when average CPU > 30%.
* Locust simulated 2,400 users for about 10 minutes against `POST /api/bid`.
* To demonstrate Auto Scaling, the demo run added a meaningless CPU computation to every bid (`burn_cpu()`), so CPU load was artificially inflated. Throughput figures therefore reflect this heavier per-request cost, not the plain service.

**Results (100-second window at 3 instances, ramping from about 600 to 900+ RPS)**

| Metric | Value |
| --- | --- |
| Average throughput | 689.11 RPS |
| Requests in window | 68,911 |
| Failures in window | 3 (>99.99% success) |
| Average response time | 294.5 ms |

The window is the difference between two Locust snapshots (160,267 and 229,178 cumulative requests); the average response time is derived as (941.96 x 229,178 - 1,220.35 x 160,267) / 68,911. Cumulative failures over the whole run were 13,097 of 229,178 requests, almost all occurring before scale-out completed (13,094 at the first snapshot). The highest `Current RPS` shown in the screenshots is 914.1.

## Notes

* This is a course project. Parameters such as the default score weights and cache TTLs are fixed values from the assignment.
* `burn_cpu()` in `routers/bidding.py` is a load-generation helper used to trigger Auto Scaling in the demo; it is disabled by default.
* There is no authentication, and `reset_all_data` is open and CORS allows any origin. Do not expose this as-is outside a demo environment.
