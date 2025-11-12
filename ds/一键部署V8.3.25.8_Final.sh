#!/bin/bash

# ============================================================
# V8.3.25.8 Final 一键部署脚本
# ============================================================

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

SERVER_USER="root"
SERVER_IP="43.100.52.142"
SERVER_DIR="/root/10-23-bot"
FRONTEND_DIR="/root/pythonc程序/my_project"

echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}🚀 V8.3.25.8 Final 一键部署${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "${YELLOW}📦 本次更新：${NC}"
echo -e "  ✅ 完善开仓统计逻辑（信号质量判断）"
echo -e "  ✅ 新增完整部署脚本（包含前端）"
echo -e "  ✅ 市场快照日期修复"
echo -e "  ✅ AI深度学习分析完整闭环"
echo ""
echo -e "${YELLOW}📝 部署步骤：${NC}"
echo -e "  1️⃣  本地代码已推送到GitHub"
echo -e "  2️⃣  SSH登录服务器执行以下命令"
echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}📋 服务器执行命令（复制粘贴）：${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
cat << 'SERVERCOMMANDS'
# 登录服务器
ssh root@43.100.52.142

# 进入项目目录
cd /root/10-23-bot

# 拉取最新代码
git pull origin main

# 更新启动脚本
cp ds/快速重启_修复版_完整.sh ~/快速重启_修复版.sh
chmod +x ~/快速重启_修复版.sh

# 重启AI机器人
supervisorctl restart ai-bot:*

# 等待3秒
sleep 3

# 检查状态
supervisorctl status ai-bot:*

# 重启前端
cd /root/pythonc程序/my_project
pkill -f "python.*my_project" || echo "没有运行中的前端"
sleep 2
nohup python3 app.py > frontend.log 2>&1 &

# 等待3秒
sleep 3

# 检查前端
ps aux | grep "python.*my_project"

# 查看前端日志（如果需要）
# tail -f frontend.log

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ 部署完成！"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "🎯 服务访问地址："
echo "  • 前端: http://43.100.52.142:5000"
echo "  • Web: http://43.100.52.142:8080"
echo ""
echo "📝 快速命令："
echo "  bash ~/快速重启_修复版.sh all        # 重启所有服务"
echo "  bash ~/快速重启_修复版.sh frontend  # 只重启前端"
echo "  bash ~/快速重启_修复版.sh backtest  # 手动回测"
echo ""
SERVERCOMMANDS

echo ""
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${YELLOW}💡 提示：${NC}"
echo -e "  1. 复制上面的命令到服务器执行"
echo -e "  2. 或者直接运行: ${GREEN}ssh root@43.100.52.142${NC}"
echo -e "  3. 服务器密码: ${GREEN}j1lUcf9TbdCzZkPL${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

