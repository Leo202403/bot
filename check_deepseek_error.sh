#!/bin/bash
echo "===== 检查DeepSeek错误日志 ====="
echo ""
echo "1. Supervisor错误日志："
tail -50 /tmp/deepseek-stderr---supervisor-*.log 2>/dev/null | tail -30
echo ""
echo "2. 最新的Python错误："
tail -50 /root/10-23-bot/ds/*.log 2>/dev/null | grep -A 10 "Error\|Exception\|Traceback" | tail -20
echo ""
echo "3. 直接运行测试："
cd /root/10-23-bot/ds
python3 -c "import sys; sys.path.insert(0, '.'); import deepseek_多币种智能版" 2>&1 | head -20
