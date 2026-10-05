# Polymarket weather paper-trading bot: dashboard + autonomous loop.
#   docker compose up -d --build      (see README "Running on a server")
# PAPER TRADING ONLY: the container forces app.mode = paper.
FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
# the bot runs as this unprivileged user; it can write only /app/data
RUN useradd --create-home --uid 1000 wxbot
COPY . .
ENV WXBOT_APP__HOST=0.0.0.0 WXBOT_APP__MODE=paper
EXPOSE 8000
# the first start can take a while: it loads observation history and fits the station
# bias/spread before the dashboard starts (deploy/docker-entrypoint.sh)
HEALTHCHECK --interval=60s --timeout=5s --start-period=30m \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')"
# the commit this image was built from (deploy/update.sh passes it), recorded with every run
ARG WXBOT_GIT_REF=""
ENV WXBOT_GIT_REF=${WXBOT_GIT_REF}
ENTRYPOINT ["/app/deploy/docker-entrypoint.sh"]
CMD ["run"]
