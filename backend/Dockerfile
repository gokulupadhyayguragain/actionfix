FROM public.ecr.aws/lambda/python:3.12

# Kiro CLI is the documented headless automation client. The Lambda never grants
# it tools; it receives only bounded, redacted diagnostic text.
RUN dnf install -y ca-certificates findutils unzip \
    && dnf clean all \
    && rm -rf /var/cache/dnf
RUN curl -fsSL https://cli.kiro.dev/install | bash
ENV PATH="/root/.local/bin:/root/.kiro/bin:/usr/local/bin:${PATH}"
RUN KIRO_BIN="$(find /root /usr/local /opt -type f -name kiro-cli -perm /111 -print -quit 2>/dev/null)" \
    && test -n "${KIRO_BIN}" \
    && KIRO_BIN_DIR="$(dirname "${KIRO_BIN}")" \
    && find "${KIRO_BIN_DIR}" -maxdepth 1 -type f -perm /111 -exec cp {} /usr/local/bin/ \; \
    && chmod 755 /usr/local/bin/kiro-cli /usr/local/bin/kiro-cli-chat \
    && kiro-cli --version

COPY app.py agent.py tools.py validation.py requirements.txt ${LAMBDA_TASK_ROOT}/

CMD ["app.lambda_handler"]
