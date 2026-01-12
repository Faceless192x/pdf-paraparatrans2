FROM mcr.microsoft.com/devcontainers/python:3.11

# Google Cloud SDK (gcloud) install (Debian/Ubuntu)
RUN apt-get update && apt-get install -y \
    apt-transport-https ca-certificates gnupg curl \
 && curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg \
    | gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg \
 && echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" \
    > /etc/apt/sources.list.d/google-cloud-sdk.list \
 && apt-get update \
 && apt-get install -y google-cloud-cli \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*
