#!/usr/bin/env python3
"""
FastAPI Server for Code Execution Engine
Run this file to start the web server only.
"""

import os
import sys
import uvicorn
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add the current directory to the Python path
sys.path.insert(0, os.path.dirname(__file__))

# Import the FastAPI app
from main import app

if __name__ == '__main__':
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    
    print("🚀 Starting FastAPI Server")
    print("=" * 60)
    print("📋 Server Configuration:")
    print(f"   Host: {host}")
    print(f"   Port: {port}")
    print(f"   URL: http://{host}:{port}")
    print("=" * 60)
    print("🎯 Supported Languages: Python, JavaScript, Java, C++, Go")
    print(f"📚 API Documentation: http://{host}:{port}/docs")
    print("🛑 Press Ctrl+C to stop the server")
    print("=" * 60)
    print()
    print("⚠️  REMINDER: Make sure to also run:")
    print("   1. Celery Worker: python celery_worker.py")
    print("   2. Callback Receiver: python callback_receiver.py")
    print("=" * 60)
    
    uvicorn.run(
        app, 
        host=host, 
        port=port,
        reload=False,  # Set to True for development
        log_level="info"
    )