# PyRedis-lite

A minimal, from-scratch Redis clone written in pure Python — no external
dependencies — communicating over the real Redis wire protocol **RESP2**.

---

## Features (v0.1)

| Command | Behaviour |
|---------|-----------|
| `PING` | Returns `+PONG` |
| `PING <msg>` | Returns a bulk-string echo of `<msg>` |
| `ECHO <msg>` | Returns a bulk-string copy of `<msg>` |

---

## Quick start

```bash
# 1. Clone & install in editable mode
git clone <repo-url>
cd pyredis-lite
pip install -e .

# 2. Start the server  (default: 127.0.0.1:6379)
python -m redis_clone.main

# 3. In another terminal, test with the official redis-cli
redis-cli PING
redis-cli ECHO "hello world"
```

---

## Architecture

```
Client (redis-cli / any RESP2 client)
        │  raw TCP bytes (RESP2 encoded)
        ▼
┌────────────────────────────────┐
│  Server  (redis_clone/main.py) │
│  _create_socket                │
│  _bind_socket                  │
│  _listen                       │
│  _accept_connections  ◄──────loop
│    └─ _handle_connection       │
│         └─ _process_command    │
└──────┬──────────────┬──────────┘
       │              │
       ▼              ▼
  Parser           ResponseBuilder
  (RESP2 in)       (RESP2 out)
```

### Key modules

| Module | Responsibility |
|--------|----------------|
| `redis_clone/main.py` | TCP server, command dispatch |
| `redis_clone/redis_parser.py` | RESP2 → `(command, args)` |
| `redis_clone/response_builder.py` | Python values → RESP2 bytes |

---

## Running the tests

```bash
pip install pytest
pytest tests/ -v
```

---

## Roadmap

- [ ] `SET` / `GET` — in-memory key-value store
- [ ] Key expiry (`EX`, `PX`, `EXAT`, `PXAT`)
- [ ] `DEL`, `EXISTS`, `KEYS`
- [ ] Persistence (RDB snapshot)
- [ ] Multi-client support (threading / asyncio)
- [ ] `LPUSH` / `RPUSH` / `LRANGE` (list type)
- [ ] Pub/Sub

---

## License

MIT
