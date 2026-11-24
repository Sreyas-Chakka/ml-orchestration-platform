# Small image for training pods: numpy + stdlib only.
FROM python:3.12-slim
RUN pip install --no-cache-dir "numpy>=1.26" && useradd -u 1000 -m trainer
WORKDIR /app
COPY train.py .
USER 1000
ENTRYPOINT ["python", "train.py"]
