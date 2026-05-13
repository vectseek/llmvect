# LLMVECT 模型发现系统 - 服务器部署指南

## 本次更新内容

1. **模型自动发现** - 每6小时自动调用厂商 /v1/models API，发现新上架模型
2. **健康探测** - 每1小时对所有模型做轻量健康检查（max_tokens=1）
3. **实时熔断** - Arena 盲测中连续3次调用失败自动禁用模型
4. **Admin后台新增「模型健康」标签页** - 可手动触发发现/探测，查看模型状态
5. **API_BASE 修复** - index.html 和 leaderboard.html 的 localhost 已改为 window.location.origin

## 部署步骤（在服务器上执行）

### Step 1: SSH 登录服务器

```bash
ssh root@你的服务器IP
```

### Step 2: 进入项目目录

```bash
cd /www/wwwroot/LLMVECT.COM/backend
source venv/bin/activate
```

### Step 3: 从 GitHub 拉取最新代码

方式A：直接 git pull（如果服务器有 git 仓库）
```bash
cd /www/wwwroot/LLMVECT.COM
git pull origin main
```

方式B：如果服务器没有 git 仓库，手动替换文件
```bash
# 先备份
cp backend/main.py backend/main.py.bak
cp backend/requirements.txt backend/requirements.txt.bak
cp frontend/index.html frontend/index.html.bak
cp frontend/leaderboard.html frontend/leaderboard.html.bak

# 从 GitHub 下载最新文件
curl -o backend/main.py https://raw.githubusercontent.com/vectseek/llmvect/main/backend/main.py
curl -o backend/requirements.txt https://raw.githubusercontent.com/vectseek/llmvect/main/backend/requirements.txt
curl -o frontend/index.html https://raw.githubusercontent.com/vectseek/llmvect/main/frontend/index.html
curl -o frontend/leaderboard.html https://raw.githubusercontent.com/vectseek/llmvect/main/frontend/leaderboard.html
```

### Step 4: 安装新依赖（apscheduler）

```bash
cd /www/wwwroot/LLMVECT.COM/backend
source venv/bin/activate
pip install apscheduler==3.10.4
```

### Step 5: 重启 uvicorn

```bash
# 找到旧进程
ps aux | grep uvicorn

# 杀掉旧进程（替换 PID 为实际值）
kill -9 旧进程PID

# 启动新进程
cd /www/wwwroot/LLMVECT.COM/backend
source venv/bin/activate
nohup python3 -m uvicorn main:app --host 0.0.0.0 --port 8001 &
```

### Step 6: 验证启动成功

```bash
# 检查进程
ps aux | grep uvicorn

# 检查日志（看有无报错）
tail -20 nohup.out

# 测试健康探测 API
curl -H "Authorization: Bearer YOUR_ADMIN_TOKEN" http://localhost:8001/api/admin/model-health
```

### Step 7: 更新 admin.html（不在 GitHub 上，需手动更新）

admin.html 不在开源仓库中（安全原因），需要在服务器上手动添加以下内容：

**7a. 添加导航标签**（在其他 nav-tab 旁边加一行）：
```html
<div class="nav-tab" onclick="switchTab('health')">🩺 模型健康</div>
```

**7b. 添加标签页内容**（在 providers tab-content 后面加）
**7c. 添加 JS 函数**（loadHealthData, triggerDiscovery, triggerHealthCheck, toggleModel）

> 最简单的方式：从本地 `frontend/admin.html` 复制到服务器

```bash
# 如果你可以用 scp 从本地上传
scp frontend/admin.html root@你的服务器IP:/www/wwwroot/LLMVECT.COM/frontend/admin.html
```

### Step 8: 测试模型发现功能

1. 登录管理后台
2. 切换到「模型健康」标签页
3. 点击「🔍 发现新模型」→ 会自动调用所有已配置 API Key 的厂商 /v1/models 接口
4. 点击「💓 健康探测」→ 会逐个测试每个模型是否可用
5. 查看模型状态列表，可手动启用/禁用

## 自动定时任务说明

启动后 APScheduler 会自动运行：
- **模型发现**：每6小时自动执行一次 run_discovery()
- **健康探测**：每1小时自动执行一次 run_health_check()

首次需要先手动点击按钮触发，后续自动运行。

## 注意事项

- 百度、科大讯飞、华为不支持 /v1/models API，这些厂商只能靠健康探测
- 健康探测会消耗少量 API 额度（每次 max_tokens=1，约1个token）
- 连续3次调用失败的模型会自动禁用，可在后台手动重新启用
- admin.html 不在 GitHub 仓库中，需单独上传到服务器
