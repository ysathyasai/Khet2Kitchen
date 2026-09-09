# Gunicorn configuration optimized for Render Single-Instance Free Tier
import os

bind = f"0.0.0.0:{os.getenv('PORT', '8000')}"
workers = 1
threads = 2
timeout = 120
graceful_timeout = 30
keepalive = 5
max_requests = 1000
max_requests_jitter = 50
worker_class = "gthread"
