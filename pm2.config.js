module.exports = {
  apps: [
    {
      name: 'fastapi-app',
      script: './start_uvicorn.sh',
      autorestart: true,
      watch: false,
      max_memory_restart: '1G', // Increase memory limit for Uvicorn
    },
    {
      name: 'celery-worker',
      script: './start_celery.sh',
      autorestart: true,
      watch: false,
      max_memory_restart: '1G', // Increase memory limit for Celery
    },
  ],
};
