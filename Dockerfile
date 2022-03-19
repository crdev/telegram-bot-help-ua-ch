FROM python:3.10-bullseye

ARG TELEGRAM_BOT_API_KEY=

ENV PORT=5000
ENV HEALTHCHECK_PORT=10000
ENV TELEGRAM_BOT_PORT=8443
ENV TELEGRAM_BOT_API_KEY=${TELEGRAM_BOT_API_KEY}
ENV USE_WEBHOOK=true

# Package installation/setup
RUN apt-get update && apt-get install -y haproxy gettext-base
STOPSIGNAL SIGUSR1

# Set up Bot filesystem and deps
WORKDIR /app
COPY *.proto *.py *.textproto haproxy.cfg.template requirements.txt run.sh ./
COPY photo photo
COPY proto proto
RUN pip3 install -r requirements.txt

EXPOSE ${PORT}/tcp

RUN chmod +x ./run.sh
CMD ./run.sh
