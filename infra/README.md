# Infra

本目录包含本地基础设施镜像配置。

- `docker-compose.local.yml`: PostgreSQL/Qdrant/NATS/MinIO/pgAdmin
- `.env.local.example`: 环境变量模板
- `postgres/init/001_backend_schema_init.sql`: 数据库初始化脚本

启动:
```powershell
cd infra
docker compose --env-file .env.local.example -f docker-compose.local.yml up -d
```
