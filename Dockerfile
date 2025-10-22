FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install dependencies
RUN pip install --no-cache-dir flask Pillow requests gunicorn

# Copy application file
COPY eink_proxy.py .

# Expose port
EXPOSE 5000

# Environment variables for configuration
ENV SOURCE_URL="http://192.168.1.199:10000/lovelace-main/einkpanelcolor?viewport=800x480"
ENV PORT=5000

# Run with gunicorn for production
CMD gunicorn --bind 0.0.0.0:${PORT} --workers 2 --timeout 120 eink_proxy:app