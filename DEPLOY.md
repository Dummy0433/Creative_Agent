# VPS 部署指南

## 一次性手动操作（Wells 需要做）

### 1. 开一台 Hetzner VPS（~5分钟）
- 注册 Hetzner Cloud: https://console.hetzner.cloud
- 新建 Server: 选 **CX22**（2核4G，€3.79/月）或 **CX32**（4核8G，€7.1/月）
- 镜像: Ubuntu 24.04
- 区域: 任意（建议 Nuremberg 或 Helsinki，延迟较低）
- SSH Key: 粘贴你的公钥（`cat ~/.ssh/id_rsa.pub`）
- 记录下分配的 **IP 地址**

### 2. 配置 GitHub Secrets
在 https://github.com/Dummy0433/Creative_Agent/settings/secrets/actions 添加：
- `VPS_HOST` = VPS 的 IP 地址
- `VPS_USER` = `root`（或你创建的用户名）
- `VPS_SSH_KEY` = 你的 SSH 私钥（`cat ~/.ssh/id_rsa`）

### 3. 初始化 VPS（SSH 进去执行一次）
```bash
ssh root@<VPS_IP>

# 安装 Docker
curl -fsSL https://get.docker.com | sh

# 克隆仓库
git clone https://github.com/Dummy0433/Creative_Agent.git /opt/gift-service
cd /opt/gift-service

# 复制 .env 文件（把本地 .env 内容粘贴进去）
nano .env

# 首次启动
docker compose up -d --build

# 验证
curl http://localhost/health
```

### 4. 后续更新（自动）
推代码到 main 分支 → GitHub Actions 自动 SSH 进 VPS → `docker compose up -d --build` → 完成。

---

## 待解决的飞书权限问题

在飞书开放平台（https://open.feishu.cn/app/cli_a9f835ced938dbd6）补充以下权限后重新发布应用：

| 权限 | 用途 |
|------|------|
| `drive:drive` 或 `bitable:app:readonly` | TABLE3 参考图下载（目前 400 报错）|
| `base:field:write` | 允许 Agent 给 Bitable 表格创建新字段（TABLE3 加 `区域` 列）|

两个权限都不影响现有主流程，补完后参考图会自动生效，APAC few-shot 质量会提升。

---

## 当前服务状态

| 服务 | 状态 |
|------|------|
| `/generate` POST | ✅ 可用（本地测试通过）|
| `/health` GET | ✅ 可用 |
| `/docs` GET | ✅ FastAPI 自动文档 |
| VPS 部署 | ⏳ 等待 Hetzner 开机 |
| CI/CD | ✅ workflow 已写好，secrets 配置后生效 |
