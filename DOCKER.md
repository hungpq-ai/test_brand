# 🐳 Docker Deployment Guide

## 📦 Quick Start

### 1. Build & Run với Docker Compose (Recommended)

```bash
# Build image
docker-compose build

# Run web dashboard
docker-compose up -d

# View logs
docker-compose logs -f

# Stop
docker-compose down
```

**Truy cập:** http://localhost:8501

---

### 2. Build & Run với Docker (Manual)

```bash
# Build image
docker build -t ai-brand-monitor .

# Run web dashboard
docker run -d \
  --name ai-brand-monitor \
  -p 8501:8501 \
  -v $(pwd)/.env:/app/.env:ro \
  -v $(pwd)/output:/app/output \
  -v $(pwd)/prompts.csv:/app/prompts.csv:ro \
  ai-brand-monitor

# View logs
docker logs -f ai-brand-monitor

# Stop & remove
docker stop ai-brand-monitor
docker rm ai-brand-monitor
```

---

## 🎯 Usage Modes

### Mode 1: Web Dashboard (Default)

```bash
docker-compose up -d
```

Truy cập: http://localhost:8501

Features:
- 📊 Overview dashboard
- ⚡ Live Query
- 🔄 Batch Run
- 📄 View Results

---

### Mode 2: CLI Batch Run

Chạy batch test một lần:

```bash
docker-compose run --rm ai-brand-monitor python main.py
```

Custom options:

```bash
# Test specific engines
docker-compose run --rm ai-brand-monitor \
  python main.py --engines chatgpt,gemini

# Test specific brands
docker-compose run --rm ai-brand-monitor \
  python main.py --brands "Mondelez,Nestlé"

# Dry run
docker-compose run --rm ai-brand-monitor \
  python main.py --dry-run
```

---

### Mode 3: Interactive Shell

Debug hoặc explore:

```bash
docker-compose run --rm ai-brand-monitor bash
```

---

## 📁 Volume Mounts

Docker container mount các thư mục:

```
Host                    Container               Mode
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
./.env          →       /app/.env               ro (read-only)
./output/       →       /app/output/            rw (read-write)
./prompts.csv   →       /app/prompts.csv        ro
./config.yaml   →       /app/config.yaml        ro
```

**Lợi ích:**
- ✅ API keys an toàn (không copy vào image)
- ✅ Results lưu ở host (persist sau khi xóa container)
- ✅ Dễ update config mà không rebuild image

---

## 🔧 Configuration

### Update API Keys

```bash
# Edit .env
nano .env

# Restart container
docker-compose restart
```

### Update Config

```bash
# Edit config.yaml
nano config.yaml

# Restart container
docker-compose restart
```

### Update Prompts

```bash
# Edit prompts.csv
nano prompts.csv

# No restart needed (mounted as volume)
```

---

## 🚀 Production Deployment

### Option 1: Docker Compose (Single Server)

```bash
# On production server
git clone <repo>
cd test_brand

# Setup .env with production API keys
cp .env.example .env
nano .env

# Run
docker-compose up -d

# Enable auto-restart on boot
docker update --restart=always ai-brand-monitor
```

---

### Option 2: Docker Swarm (Multi-Server)

```bash
# Initialize swarm
docker swarm init

# Deploy stack
docker stack deploy -c docker-compose.yml ai-brand-monitor

# Check status
docker stack services ai-brand-monitor

# Remove stack
docker stack rm ai-brand-monitor
```

---

### Option 3: Kubernetes

Create `k8s-deployment.yaml`:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: ai-brand-monitor
spec:
  replicas: 1
  selector:
    matchLabels:
      app: ai-brand-monitor
  template:
    metadata:
      labels:
        app: ai-brand-monitor
    spec:
      containers:
      - name: ai-brand-monitor
        image: ai-brand-monitor:latest
        ports:
        - containerPort: 8501
        env:
        - name: CHATGPT_API_KEY
          valueFrom:
            secretKeyRef:
              name: api-keys
              key: chatgpt
        - name: GOOGLE_API_KEY
          valueFrom:
            secretKeyRef:
              name: api-keys
              key: google
        volumeMounts:
        - name: output
          mountPath: /app/output
      volumes:
      - name: output
        persistentVolumeClaim:
          claimName: ai-brand-monitor-output
---
apiVersion: v1
kind: Service
metadata:
  name: ai-brand-monitor
spec:
  selector:
    app: ai-brand-monitor
  ports:
  - port: 80
    targetPort: 8501
  type: LoadBalancer
```

Deploy:

```bash
kubectl apply -f k8s-deployment.yaml
```

---

## 🐛 Troubleshooting

### Container không start

```bash
# Check logs
docker-compose logs

# Check errors
docker-compose logs ai-brand-monitor --tail=50
```

### API keys không hoạt động

```bash
# Verify .env mounted
docker-compose exec ai-brand-monitor cat /app/.env

# Check environment variables
docker-compose exec ai-brand-monitor env | grep API_KEY
```

### Port 8501 already in use

```bash
# Change port in docker-compose.yml
ports:
  - "8502:8501"  # Use different host port

# Or stop conflicting service
lsof -i :8501
kill -9 <PID>
```

### Permission denied on output/

```bash
# Fix permissions on host
chmod 777 output/

# Or run as specific user
docker-compose run --user $(id -u):$(id -g) ...
```

---

## 📊 Monitoring

### Health Check

```bash
# Check container health
docker-compose ps

# Manual health check
curl http://localhost:8501/
```

### Resource Usage

```bash
# Monitor CPU/Memory
docker stats ai-brand-monitor

# Detailed info
docker inspect ai-brand-monitor
```

### Logs

```bash
# Follow logs
docker-compose logs -f

# Last 100 lines
docker-compose logs --tail=100

# Export logs
docker-compose logs > app.log 2>&1
```

---

## 🔄 Updates

### Update Code

```bash
# Pull latest code
git pull

# Rebuild & restart
docker-compose down
docker-compose build
docker-compose up -d
```

### Update Dependencies

```bash
# Update requirements.txt
nano requirements.txt

# Rebuild
docker-compose build --no-cache
docker-compose up -d
```

---

## 🗑️ Cleanup

### Remove Container

```bash
docker-compose down
```

### Remove Container + Volumes

```bash
docker-compose down -v
```

### Remove Image

```bash
docker rmi ai-brand-monitor
```

### Full Cleanup

```bash
# Stop & remove everything
docker-compose down -v
docker rmi ai-brand-monitor
docker system prune -af
```

---

## 💡 Tips

1. **Keep .env secure**: Add to .gitignore, never commit API keys
2. **Backup output/**: Results are valuable, backup regularly
3. **Monitor costs**: Track API usage in dashboard
4. **Use volumes**: Keep data outside container for persistence
5. **Health checks**: Container auto-restarts if unhealthy

---

## 🔗 Links

- Docker Hub: (push image here for easy deployment)
- GitHub: (repo link)
- Docs: SETUP.md, README.md
