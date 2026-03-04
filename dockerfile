FROM astral/uv:python3.12-trixie-slim

RUN apt-get update -y && \
  apt-get install -y --no-install-recommends \
  git \
  && \
  apt-get clean && \
  rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY uv.lock .
COPY pyproject.toml .
RUN uv sync --frozen
ADD server /app/

EXPOSE 8000

CMD ["uv", "run", "main.py"]
