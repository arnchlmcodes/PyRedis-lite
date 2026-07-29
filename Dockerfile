# ---------- build stage ----------
FROM python:3.12-slim AS builder

WORKDIR /app

COPY requirements-dev.txt .
RUN pip install --no-cache-dir -r requirements-dev.txt

COPY . .
RUN pip install --no-cache-dir -e .[dev]

# ---------- runtime / test stage ----------
FROM builder AS test

WORKDIR /app

CMD ["pytest", "tests/", "-v", "--tb=short"]
