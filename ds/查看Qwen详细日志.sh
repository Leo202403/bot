#!/bin/bash

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "查看 Qwen 详细错误日志"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "=== 1. Supervisor stderr 日志 ==="
if ls /var/log/supervisor/qwen-stderr*.log 1> /dev/null 2>&1; then
    echo "最新 stderr 日志 (最后 100 行):"
    tail -100 /var/log/supervisor/qwen-stderr*.log | head -100
else
    echo "❌ 未找到 stderr 日志"
fi
echo ""

echo "=== 2. Supervisor stdout 日志 ==="
if ls /var/log/supervisor/qwen-stdout*.log 1> /dev/null 2>&1; then
    echo "最新 stdout 日志 (最后 50 行):"
    tail -50 /var/log/supervisor/qwen-stdout*.log | head -50
else
    echo "❌ 未找到 stdout 日志"
fi
echo ""

echo "=== 3. 尝试直接运行 Python 脚本 ==="
echo "正在尝试..."
cd /root/10-23-bot/ds
python3 qwen_多币种智能版.py 2>&1 | head -200 &
PID=$!
sleep 3
kill $PID 2>/dev/null

echo ""
echo "=== 4. 检查 Python 语法 ==="
python3 -m py_compile qwen_多币种智能版.py 2>&1 | head -50

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
