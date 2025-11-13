#!/bin/bash

# ============================================================
# 快速重启脚本 - 完整版（包含前端）
# ============================================================

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

BOT_DIR="/root/10-23-bot/ds"
FRONTEND_DIR="/root/pythonc程序/my_project"

# 显示使用方法
show_usage() {
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${YELLOW}🚀 快速重启脚本 - 完整版${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    echo -e "${GREEN}【重启服务】${NC}"
    echo -e "  ${YELLOW}bash ~/快速重启_修复版.sh all${NC}          # 重启全部服务（AI+前端+Web）"
    echo -e "  ${YELLOW}bash ~/快速重启_修复版.sh bots${NC}         # 重启所有AI机器人"
    echo -e "  ${YELLOW}bash ~/快速重启_修复版.sh deepseek${NC}     # 只重启DeepSeek"
    echo -e "  ${YELLOW}bash ~/快速重启_修复版.sh qwen${NC}         # 只重启Qwen"
    echo -e "  ${YELLOW}bash ~/快速重启_修复版.sh web${NC}          # 只重启Web面板"
    echo -e "  ${YELLOW}bash ~/快速重启_修复版.sh frontend${NC}     # 只重启前端"
    echo ""
    echo -e "${GREEN}【手动回测】${NC}"
    echo -e "  ${YELLOW}bash ~/快速重启_修复版.sh backtest${NC}              # 回测所有模型"
    echo -e "  ${YELLOW}bash ~/快速重启_修复版.sh backtest-deepseek${NC}    # 只回测DeepSeek"
    echo -e "  ${YELLOW}bash ~/快速重启_修复版.sh backtest-qwen${NC}        # 只回测Qwen"
    echo ""
    echo -e "${GREEN}【回测+重启】⭐ 推荐（新参数立即生效）${NC}"
    echo -e "  ${YELLOW}bash ~/快速重启_修复版.sh backtest-restart-all${NC}       # 回测所有并重启"
    echo -e "  ${YELLOW}bash ~/快速重启_修复版.sh backtest-restart-deepseek${NC}  # 回测DeepSeek并重启"
    echo -e "  ${YELLOW}bash ~/快速重启_修复版.sh backtest-restart-qwen${NC}      # 回测Qwen并重启"
    echo ""
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

# 重启前端
restart_frontend() {
    echo -e "\n${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${YELLOW}🌐 重启前端服务${NC}"
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    
    if [ ! -d "$FRONTEND_DIR" ]; then
        echo -e "${RED}❌ 前端目录不存在: $FRONTEND_DIR${NC}"
        return 1
    fi
    
    # 停止现有前端进程
    echo -e "${YELLOW}  → 停止现有前端进程...${NC}"
    pkill -f "python.*my_project" || echo "  ℹ️  没有运行中的前端进程"
    sleep 2
    
    # 前端通过supervisor管理，直接重启
    echo -e "${YELLOW}  → 重启前端服务（supervisor: web）...${NC}"
    supervisorctl restart web
    sleep 3
    
    # 检查启动状态
    if supervisorctl status web | grep -q "RUNNING"; then
        echo -e "${GREEN}  ✅ 前端服务启动成功${NC}"
        echo -e "${GREEN}  📊 前端访问地址: http://43.100.52.142 (端口80)${NC}"
        return 0
    else
        echo -e "${RED}  ❌ 前端服务启动失败，请检查日志：${NC}"
        echo -e "${RED}     tail -f /var/log/gunicorn/error.log${NC}"
        return 1
    fi
}

# 重启Web面板（等同于前端）
restart_web() {
    echo -e "\n${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${YELLOW}🌐 重启Web面板（前端）${NC}"
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    
    supervisorctl restart web
    sleep 2
    supervisorctl status web
}

# 重启所有AI机器人
restart_bots() {
    echo -e "\n${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${YELLOW}🤖 重启所有AI机器人${NC}"
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    
    supervisorctl restart deepseek qwen
    sleep 2
    supervisorctl status deepseek qwen
}

# 重启DeepSeek
restart_deepseek() {
    echo -e "\n${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${YELLOW}🧠 重启DeepSeek${NC}"
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    
    supervisorctl restart deepseek
    sleep 2
    supervisorctl status deepseek
}

# 重启Qwen
restart_qwen() {
    echo -e "\n${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${YELLOW}🧠 重启Qwen${NC}"
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    
    supervisorctl restart qwen
    sleep 2
    supervisorctl status qwen
}

# 手动回测
run_backtest() {
    local model=$1
    
    echo -e "\n${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${YELLOW}🔬 手动回测${model:+: $model}${NC}"
    echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    
    cd "$BOT_DIR"
    
    # 🔧 V8.3.25.9: 修复回测命令 - 使用环境变量MANUAL_BACKTEST=true
    if [ -z "$model" ]; then
        # 回测所有模型
        echo -e "${BLUE}  ℹ️  🔬 手动回测所有模型...${NC}\n"
        
        echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        echo -e "${BLUE}回测模型1: Qwen${NC}"
        echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"
        MANUAL_BACKTEST=true python3 qwen_多币种智能版.py
        
        echo -e "\n${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        echo -e "${BLUE}回测模型2: DeepSeek${NC}"
        echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"
        MANUAL_BACKTEST=true python3 deepseek_多币种智能版.py
        
    elif [ "$model" == "deepseek" ]; then
        echo -e "${BLUE}  ℹ️  🔬 手动回测DeepSeek...${NC}\n"
        MANUAL_BACKTEST=true python3 deepseek_多币种智能版.py
    elif [ "$model" == "qwen" ]; then
        echo -e "${BLUE}  ℹ️  🔬 手动回测Qwen...${NC}\n"
        MANUAL_BACKTEST=true python3 qwen_多币种智能版.py
    fi
    
    echo -e "\n${GREEN}✅ 回测完成${NC}"
}

# 主逻辑
case "$1" in
    "all")
        echo -e "${GREEN}🚀 重启全部服务（AI机器人 + Web面板 + 前端）${NC}"
        restart_bots
        restart_web
        restart_frontend
        echo -e "\n${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        echo -e "${GREEN}✅ 全部服务重启完成${NC}"
        echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        ;;
    "bots")
        restart_bots
        ;;
    "deepseek")
        restart_deepseek
        ;;
    "qwen")
        restart_qwen
        ;;
    "web")
        restart_web
        ;;
    "frontend")
        restart_frontend
        ;;
    "backtest")
        run_backtest
        ;;
    "backtest-deepseek")
        run_backtest "deepseek"
        ;;
    "backtest-qwen")
        run_backtest "qwen"
        ;;
    "backtest-restart-all")
        run_backtest
        echo -e "\n${YELLOW}🔄 重启所有服务（应用新参数）${NC}"
        restart_bots
        restart_web
        restart_frontend
        ;;
    "backtest-restart-deepseek")
        run_backtest "deepseek"
        echo -e "\n${YELLOW}🔄 重启DeepSeek（应用新参数）${NC}"
        restart_deepseek
        ;;
    "backtest-restart-qwen")
        run_backtest "qwen"
        echo -e "\n${YELLOW}🔄 重启Qwen（应用新参数）${NC}"
        restart_qwen
        ;;
    *)
        show_usage
        ;;
esac

