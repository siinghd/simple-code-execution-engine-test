#!/usr/bin/env python3
"""
Celery Worker for Code Execution Engine
Run this file to start the background worker process.
"""

import os
import sys
from celery import Celery
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add the current directory to the Python path
sys.path.insert(0, os.path.dirname(__file__))

# Import the main Celery app
from main import celery

if __name__ == '__main__':
    # Start the Celery worker
    print("🚀 Starting Celery Worker for Code Execution Engine")
    print("=" * 60)
    print("📋 Worker Configuration:")
    print(f"   Broker: {os.getenv('CELERY_BROKER_URL', 'redis://localhost:6379/0')}")
    print(f"   Backend: {os.getenv('CELERY_RESULT_BACKEND', 'redis://localhost:6379/0')}")
    print("=" * 60)
    print("✅ Worker is ready to process code execution tasks!")
    print("🛑 Press Ctrl+C to stop the worker")
    print("=" * 60)
    
    # Start worker with appropriate settings
    celery.worker_main([
        'worker',
        '--loglevel=info',
        '--concurrency=4',  # Adjust based on your system
        '--prefetch-multiplier=1',  # Process one task at a time
        '--max-tasks-per-child=100',  # Restart worker after 100 tasks to prevent memory leaks
        '--time-limit=300',  # Hard time limit of 5 minutes per task
        '--soft-time-limit=240',  # Soft time limit of 4 minutes per task
        '--queues=code_execution',  # Listen only to our specific queue
        '--hostname=code_execution_worker@%h',  # Unique hostname
    ])