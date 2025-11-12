#!/bin/bash
# 【V8.3.25.8】一键部署脚本 - 完整的开平仓时机分析

set -e  # 遇到错误立即退出

SERVER_IP="47.89.247.51"
SERVER_USER="root"
REMOTE_PATH="/root/10-23-bot"

echo "========================================"
echo " 🚀 V8.3.25.8 部署脚本"
echo "========================================"
echo ""
echo "📦 本次更新："
echo "  ✅ 重构开平仓时机分析逻辑（对比市场机会vs AI决策）"
echo "  ✅ 新增entry_exit_timing_analyzer_v2.py模块"
echo "  ✅ 邮件合并开平仓表格（统一视图）"
echo "  ✅ 修复Qwen读取开仓数据bug"
echo ""

# Step 1: SSH到服务器并拉取最新代码
echo "📥 Step 1/4: 拉取最新代码..."
ssh ${SERVER_USER}@${SERVER_IP} << 'ENDSSH'
cd /root/10-23-bot
git pull origin main
echo "✅ 代码更新完成"
ENDSSH

# Step 2: 重启服务
echo ""
echo "🔄 Step 2/4: 重启AI服务..."
ssh ${SERVER_USER}@${SERVER_IP} << 'ENDSSH'
supervisorctl restart ai-bot:*
echo "✅ 服务重启完成"
ENDSSH

# Step 3: 检查服务状态
echo ""
echo "🔍 Step 3/4: 检查服务状态..."
ssh ${SERVER_USER}@${SERVER_IP} << 'ENDSSH'
sleep 3
supervisorctl status ai-bot:*
ENDSSH

# Step 4: 查看启动日志
echo ""
echo "📋 Step 4/4: 查看最近日志..."
ssh ${SERVER_USER}@${SERVER_IP} << 'ENDSSH'
echo ""
echo "=== DeepSeek 最近日志 ==="
tail -30 /root/10-23-bot/ds/logs/deepseek_trading.log | grep -E "V8.3.25|开平仓时机|entry_exit" || echo "暂无相关日志"
echo ""
echo "=== Qwen 最近日志 ==="
tail -30 /root/10-23-bot/ds/logs/qwen_trading.log | grep -E "V8.3.25|开平仓时机|entry_exit" || echo "暂无相关日志"
ENDSSH

echo ""
echo "========================================"
echo " ✅ 部署完成！"
echo "========================================"
echo ""
echo "📝 下一步："
echo "  1. 运行手动回测测试新功能："
echo "     bash ~/快速重启_修复版.sh backtest"
echo ""
echo "  2. 查看完整日志："
echo "     tail -f /root/10-23-bot/ds/logs/deepseek_trading.log"
echo ""
echo "  3. 明天早上8:05查看回测邮件："
echo "     - 检查是否有统一的开平仓分析表格"
echo "     - 确认Qwen能正确读取开仓数据"
echo ""

