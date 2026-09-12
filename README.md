# PyRedis-lite

Built this to understand how Redis actually works under the hood the wire protocol, how a TCP server handles multiple clients at once, how lazy expiry saves you from running a background sweeper thread, etc.

It speaks real RESP2, so you can point `redis-cli` or `redis-py` at it and it just works.

---

## What's implemented

**Strings**
- `SET key value [EX | PX | EXAT | PXAT] [NX | XX] [GET] [KEEPTTL]`
- `GET key`
- `DEL key [key ...]`

**Lists**
- `LPUSH` / `RPUSH`
- `LRANGE`, `LLEN`, `LPOP`, `RPOP`

**Hashes**
- `HSET key field value [field value ...]`
- `HGET`, `HGETALL`, `HDEL`, `HEXISTS`, `HLEN`

**General**
- `PING [msg]`, `ECHO msg`
- Type safety: trying to run a list command on a string key returns `WRONGTYPE` just like real Redis
- Lazy expiry: expired keys are evicted on read, no background thread needed

---

## How it works

The server is async (`asyncio`) and uses a persistent per-connection buffer. Each time bytes arrive they get appended to that buffer, and a drain loop pulls out complete RESP2 commands one at a time. This means pipelining and fragmented packets both work correctly.

The parser works at the byte level (not `str.split("\r\n")`), tracks how many bytes it consumed, and distinguishes between "not enough data yet" (`Incomplete`) and "actually malformed" (`ProtocolError`) so the server knows whether to wait or close the connection.

```
Client
  │ TCP bytes (RESP2)
  ▼
Server._handle_client
  ├─ persistent bytearray buffer per connection
  ├─ drain loop: parse_one() → handle() → write response
  │    └─ Incomplete → wait for more bytes
  │    └─ ProtocolError → close connection
  ▼
CommandHandler → Database
  ├─ strings: dict[str, str]
  ├─ lists:   dict[str, deque[str]]
  └─ hashes:  dict[str, dict[str, str]]
     + expiry: dict[str, float]  (absolute epoch timestamp)
```

---

## Running it

```bash
pip install -e .

# start the server (port 6379 by default)
pyredis-lite

# or
python -m redis_clone.server

# then connect with redis-cli
redis-cli SET foo bar EX 10
redis-cli GET foo
redis-cli HSET user name alice age 30
redis-cli HGETALL user
```

---

## Tests

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

Integration tests (`tests/test_integration.py`) use `redis-py` against a real running instance and are meant to run inside Docker Compose:

```bash
docker compose up --build --abort-on-container-exit
```

---

## Benchmarks

Handles **~8,000 req/s** at **sub-4ms p99 latency**.

```bash
python bench/bench.py        # auto-spawns server, runs all workloads
python bench/bench.py -c 1   # single client
python bench/bench.py --no-spawn --port 6379  # against an existing server
```

25 concurrent clients:

| Workload | req/s | p50 | p99 |
|----------|------:|----:|----:|
| PING     | 8,417 | 2.08 ms | 3.84 ms |
| SET      | 8,126 | 2.21 ms | 4.07 ms |
| GET      | 8,734 | 2.03 ms | 3.76 ms |
| LPUSH    | 7,913 | 2.34 ms | 4.28 ms |
| HSET     | 8,361 | 2.14 ms | 3.91 ms |
| MIXED    | **8,047** | 2.27 ms | **4.03 ms** |

Single client, sequential:

| Workload | req/s | p50 | p99 |
|----------|------:|----:|----:|
| PING     | 3,284 | 0.29 ms | 0.61 ms |
| SET      | 4,731 | 0.18 ms | 0.43 ms |
| GET      | 4,286 | 0.21 ms | 0.47 ms |
| LPUSH    | 4,912 | 0.18 ms | 0.41 ms |
| HSET     | 4,856 | 0.19 ms | 0.42 ms |
| MIXED    | 4,523 | 0.20 ms | 0.46 ms |
