# ── Telegram Premium Referral Bot — Railway Deployment ──────────────────────
FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy bot source code
COPY telegram-bot/ ./

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Run the bot in polling mode (no port needed)
CMD ["python", "main.py"]
