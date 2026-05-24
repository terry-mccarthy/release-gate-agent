FROM python:3.12-slim
WORKDIR /app

# Install MCP + gateway service deps
COPY services/validator_server/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt

# Install harness packages as proper packages
COPY packages/harness-gateway ./packages/harness-gateway
COPY packages/harness-validator ./packages/harness-validator
RUN pip install ./packages/harness-gateway "./packages/harness-validator[ollama]"

# Copy policy + prompts so the agent can load them at runtime
COPY policies/release_policy.yaml ./policies/release_policy.yaml
COPY prompts/risk_classifier.md ./prompts/risk_classifier.md

COPY services/validator_server/server.py .

ENV POLICY_FILE=/app/policies/release_policy.yaml
ENV PROMPTS_DIR=/app/prompts

CMD ["python", "server.py"]
