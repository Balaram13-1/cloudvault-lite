#!/usr/bin/env bash
# Rebuilds and restarts the CloudVault Lite container on the server.
# Runs on the EC2 instance, started by GitHub Actions through AWS Systems Manager.
set -euo pipefail

cd "$(dirname "$0")"

docker build -t cloudvault-lite .

docker rm -f cloudvault 2>/dev/null || true
docker run -d --name cloudvault --restart unless-stopped -p 80:8000 \
  --env-file .env -v cloudvault-data:/data \
  --log-driver awslogs \
  --log-opt awslogs-region=ap-south-1 \
  --log-opt awslogs-group=/cloudvault-lite/app \
  --log-opt awslogs-stream=cloudvault \
  --log-opt awslogs-create-group=true \
  cloudvault-lite

# Remove layers left over from old builds (the disk is small)
docker image prune -f > /dev/null

for _ in $(seq 1 20); do
  if curl -fsS http://localhost/health > /dev/null; then
    echo "Deployed: app is healthy"
    exit 0
  fi
  sleep 2
done

echo "Deploy failed: health check did not pass. Last container logs:"
docker logs --tail 50 cloudvault
exit 1
