FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Certificado do RDS, válido em todas as regiões. O caminho entra na task por DB_SSL_CA.
RUN python -c "import urllib.request; urllib.request.urlretrieve('https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem', '/app/rds-ca.pem')"
COPY *.py index.html ./
RUN useradd --create-home app
USER app
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"
# Keep-alive maior que os 60 s de ociosidade do ALB: quem fecha a conexão parada tem que ser o ALB.
# Com o padrão do uvicorn (5 s), o ALB pode reaproveitar uma conexão no instante em que ela fecha, e dá 502.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-keep-alive", "65"]
