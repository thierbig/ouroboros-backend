FROM python:3.12-slim

WORKDIR /app

# System deps for building native modules + git (needed by forge install)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl unzip git ca-certificates bash \
    && rm -rf /var/lib/apt/lists/*

# Node.js (for npx / netlify-cli)
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Bun
RUN curl -fsSL https://bun.sh/install | bash
ENV PATH="/root/.bun/bin:${PATH}"

# Foundry (forge, cast)
RUN curl -L https://foundry.paradigm.xyz | bash \
    && /root/.foundry/bin/foundryup
ENV PATH="/root/.foundry/bin:${PATH}"

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
