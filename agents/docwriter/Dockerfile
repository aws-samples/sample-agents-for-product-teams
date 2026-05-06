FROM python:3.12-slim@sha256:46cb7cc2877e60fbd5e21a9ae6115c30ace7a077b9f8772da879e4590c18c2e3

RUN groupadd --system --gid 1001 agent \
 && useradd --system --uid 1001 --gid agent --no-create-home --shell /sbin/nologin agent

WORKDIR /app

COPY docwriter/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=agent:agent shared/ /app/shared/
COPY --chown=agent:agent docwriter/ /app/

EXPOSE 8080

USER agent

CMD ["opentelemetry-instrument", "python", "agent.py"]
