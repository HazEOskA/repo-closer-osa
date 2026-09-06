FROM google/cloud-sdk:slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN python3 -m pip install --no-cache-dir .
CMD ["python3", "-m", "uvicorn", "repo_closer.api:app", "--host", "0.0.0.0", "--port", "8080"]
