#!/bin/bash

echo "========================================"
echo "🚀 部署 V8.3.25.13 - AI决策理由显示优化"
echo "========================================"

cd /root/10-23-bot

echo ""
echo "📥 拉取最新代码..."
git pull

echo ""
echo "🔄 重启AI进程..."
supervisorctl restart qwen_ai
supervisorctl restart deepseek_ai

echo ""
echo "📊 查看进程状态..."
supervisorctl status qwen_ai deepseek_ai

echo ""
echo "✅ 部署完成！"
echo ""
echo "【本次更新】"
echo "  ✓ 调试输出新增AI决策理由显示"
echo "  ✓ 包含开仓理由和平仓理由（前100字符）"
echo ""
echo "【验证方法】"
echo "  bash ~/快速重启_修复版.sh backtest"
echo "  查看输出中的：🔍 调试：前3笔交易数据样本（含AI决策）"
echo ""

