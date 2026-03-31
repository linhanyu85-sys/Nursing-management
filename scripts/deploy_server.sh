#!/bin/bash
# 服务器部署脚本 - Ubuntu 24.04
# 用法: ./deploy_server.sh

set -e

SERVER_IP="47.84.99.189"
SERVER_PASS="Linhanyu2005"
REMOTE_DIR="/opt/ai-nursing"

echo "=== AI护理系统服务器部署脚本 ==="
echo "目标服务器: $SERVER_IP"
echo ""

# 检查本地依赖
if ! command -v sshpass &> /dev/null; then
    echo "正在安装 sshpass..."
    apt-get update && apt-get install -y sshpass
fi

# 创建远程目录
echo "[1/6] 创建远程目录..."
sshpass -p "$SERVER_PASS" ssh -o StrictHostKeyChecking=no root@$SERVER_IP "mkdir -p $REMOTE_DIR"

# 上传项目文件
echo "[2/6] 上传项目文件..."
sshpass -p "$SERVER_PASS" scp -o StrictHostKeyChecking=no -r \
    apps/ services/ infra/ scripts/ data/ prompts/ docs/ README.md .env.example \
    root@$SERVER_IP:$REMOTE_DIR/

# 上传Docker配置
echo "[3/6] 上传Docker配置..."
sshpass -p "$SERVER_PASS" scp -o StrictHostKeyChecking=no \
    docker-compose.local.yml \
    root@$SERVER_IP:$REMOTE_DIR/docker-compose.yml

# 在服务器上执行部署
echo "[4/6] 在服务器上执行部署..."
sshpass -p "$SERVER_PASS" ssh -o StrictHostKeyChecking=no root@$SERVER_IP << 'REMOTE_SCRIPT'

cd /opt/ai-nursing

# 安装Docker和Docker Compose
if ! command -v docker &> /dev/null; then
    echo "安装Docker..."
    curl -fsSL https://get.docker.com | sh
    systemctl enable docker
    systemctl start docker
fi

# 创建环境文件
if [ ! -f .env.local ]; then
    cp .env.example .env.local
    echo "请编辑 .env.local 文件配置环境变量"
fi

# 启动基础设施
echo "启动基础设施..."
docker-compose up -d postgres qdrant nats minio

# 等待数据库就绪
echo "等待数据库就绪..."
sleep 10

# 安装Python依赖并启动后端服务
echo "安装Python依赖..."
apt-get update
apt-get install -y python3-pip python3-venv

for svc in api-gateway auth-service patient-context-service agent-orchestrator handover-service recommendation-service document-service collaboration-service audit-service asr-service tts-service device-gateway multimodal-med-service; do
    echo "配置 $svc..."
    cd services/$svc
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt -q
    deactivate
    cd /opt/ai-nursing
done

echo "启动后端服务..."
# 使用systemd或supervisor管理服务
# 这里创建简单的启动脚本
cat > start_services.sh << 'EOF'
#!/bin/bash
cd /opt/ai-nursing

# 启动各个服务
nohup bash -c 'cd services/api-gateway && source venv/bin/activate && uvicorn app.main:app --host 0.0.0.0 --port 8000' > logs/api-gateway.log 2>&1 &
nohup bash -c 'cd services/auth-service && source venv/bin/activate && uvicorn app.main:app --host 0.0.0.0 --port 8012' > logs/auth.log 2>&1 &
nohup bash -c 'cd services/patient-context-service && source venv/bin/activate && uvicorn app.main:app --host 0.0.0.0 --port 8002' > logs/patient.log 2>&1 &
nohup bash -c 'cd services/agent-orchestrator && source venv/bin/activate && uvicorn app.main:app --host 0.0.0.0 --port 8003' > logs/agent.log 2>&1 &
nohup bash -c 'cd services/handover-service && source venv/bin/activate && uvicorn app.main:app --host 0.0.0.0 --port 8004' > logs/handover.log 2>&1 &
nohup bash -c 'cd services/recommendation-service && source venv/bin/activate && uvicorn app.main:app --host 0.0.0.0 --port 8005' > logs/recommendation.log 2>&1 &
nohup bash -c 'cd services/document-service && source venv/bin/activate && uvicorn app.main:app --host 0.0.0.0 --port 8006' > logs/document.log 2>&1 &
nohup bash -c 'cd services/collaboration-service && source venv/bin/activate && uvicorn app.main:app --host 0.0.0.0 --port 8007' > logs/collaboration.log 2>&1 &
nohup bash -c 'cd services/audit-service && source venv/bin/activate && uvicorn app.main:app --host 0.0.0.0 --port 8011' > logs/audit.log 2>&1 &
nohup bash -c 'cd services/asr-service && source venv/bin/activate && uvicorn app.main:app --host 0.0.0.0 --port 8008' > logs/asr.log 2>&1 &
nohup bash -c 'cd services/tts-service && source venv/bin/activate && uvicorn app.main:app --host 0.0.0.0 --port 8009' > logs/tts.log 2>&1 &
nohup bash -c 'cd services/device-gateway && source venv/bin/activate && uvicorn app.main:app --host 0.0.0.0 --port 8013' > logs/device.log 2>&1 &
nohup bash -c 'cd services/multimodal-med-service && source venv/bin/activate && uvicorn app.main:app --host 0.0.0.0 --port 8010' > logs/multimodal.log 2>&1 &

echo "所有服务已启动"
EOF
chmod +x start_services.sh

mkdir -p logs

echo "=== 部署完成 ==="
echo ""
echo "请执行以下操作："
echo "1. 编辑 /opt/ai-nursing/.env.local 配置环境变量"
echo "2. 运行 ./start_services.sh 启动后端服务"
echo "3. 检查日志: tail -f logs/*.log"

REMOTE_SCRIPT

echo ""
echo "=== 部署脚本执行完成 ==="
echo "服务器: $SERVER_IP"
echo "部署目录: $REMOTE_DIR"
echo ""
echo "下一步："
echo "1. SSH登录服务器: ssh root@$SERVER_IP"
echo "2. 编辑配置: nano /opt/ai-nursing/.env.local"
echo "3. 启动服务: cd /opt/ai-nursing && ./start_services.sh"
