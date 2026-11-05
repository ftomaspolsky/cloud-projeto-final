FROM python:3.12-slim
WORKDIR /testes
COPY app/atendimento/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt pytest==8.3.4 requests==2.32.3
COPY app/atendimento/ /app/atendimento/
COPY tests/ .
ENV PYTHONPATH=/app/atendimento
CMD ["pytest", "-v", "-p", "no:cacheprovider", "."]
