# Semantic scoring service (optional PyTorch stack; MOCK mode avoids heavy model load in CI-like images).
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    RGEE_MOCK_QUESTION_ANALYSIS=1

WORKDIR /srv/RGEE_Analysis_Agent

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc g++ \
    && rm -rf /var/lib/apt/lists/*

COPY RGEE_Analysis_Agent/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY RGEE_Analysis_Agent/app ./app

EXPOSE 8010

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8010"]
