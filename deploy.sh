#!/bin/bash
# LLMVECT 一键部署脚本 - 腾讯云 + 宝塔面板
# 使用: bash deploy.sh

set -e
PROJECT_DIR="/www/wwwroot/llmvect"
BACKEND_DIR="$PROJECT_DIR/backend"

echo "===== LLMVECT 部署开始 ====="

# 1. 创建虚拟环境
cd $BACKEND_DIR
if [ ! -d "venv" ]; then
    echo "[1/5] 创建 Python 虚拟环境..."
    python3 -m venv venv
else
    echo "[1/5] 虚拟环境已存在，跳过"
fi

# 2. 安装依赖
echo "[2/5] 安装 Python 依赖..."
source venv/bin/activate
pip install -r requirements.txt -q

# 3. 创建 systemd 服务
echo "[3/5] 配置 systemd 服务..."
cat > /etc/systemd/system/llmvect.service << EOF
[Unit]
Description=LLMVECT FastAPI Server
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$BACKEND_DIR
EnvironmentFile=$BACKEND_DIR/.env
ExecStart=$BACKEND_DIR/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8001 --workers 2
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable llmvect

# 4. 检查 .env 文件
if [ ! -f "$BACKEND_DIR/.env" ]; then
    echo "[4/5] 创建 .env 模板..."
    cat > $BACKEND_DIR/.env << 'ENVEOF'
# ===== 国内模型 API Keys =====
DASHSCOPE_API_KEY=your_dashscope_key
BAIDU_API_KEY=your_baidu_key
TENCENT_API_KEY=your_tencent_key
ZHIPU_API_KEY=your_zhipu_key
MOONSHOT_API_KEY=your_moonshot_key
DEEPSEEK_API_KEY=your_deepseek_key
STEPFUN_API_KEY=your_stepfun_key
BAICHUAN_API_KEY=your_baichuan_key
MINIMAX_API_KEY=your_minimax_key
XIAOMI_API_KEY=your_xiaomi_key
DOUBAO_API_KEY=your_doubao_key
YI_API_KEY=your_yi_key
SILICONFLOW_API_KEY=your_siliconflow_key

# ===== 国际模型 API Keys =====
OPENAI_API_KEY=your_openai_key
ANTHROPIC_API_KEY=your_anthropic_key
GOOGLE_API_KEY=your_google_key
MISTRAL_API_KEY=your_mistral_key
COHERE_API_KEY=your_cohere_key
GROQ_API_KEY=your_groq_key
ENVEOF
    echo "⚠️  请编辑 $BACKEND_DIR/.env 填入真实 API Key！"
else
    echo "[4/5] .env 已存在，跳过"
fi

# 5. 启动服务
echo "[5/5] 启动服务..."
systemctl start llmvect
sleep 2
systemctl status llmvect --no-pager

echo ""
echo "===== 部署完成 ====="
echo "后端运行在: http://127.0.0.1:8001"
echo ""
echo "下一步："
echo "1. 编辑 $BACKEND_DIR/.env 填入 API Key"
echo "2. 宝塔面板 → 网站 → 添加站点 → 配置 Nginx 反代"
echo "3. 重启服务: systemctl restart llmvect"
