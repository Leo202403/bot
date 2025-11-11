#!/bin/bash

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "检查 Qwen AI 启动错误"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "=== 1. 检查 Supervisor 状态 ==="
supervisorctl status qwen
echo ""

echo "=== 2. 查看 Qwen 错误日志（最后 50 行）==="
if [ -f "/root/10-23-bot/ds/qwen_error.log" ]; then
    echo "--- qwen_error.log ---"
    tail -50 /root/10-23-bot/ds/qwen_error.log
else
    echo "❌ 未找到 qwen_error.log"
fi
echo ""

echo "=== 3. 查看 Qwen 标准输出日志（最后 50 行）==="
if [ -f "/root/10-23-bot/ds/qwen_output.log" ]; then
    echo "--- qwen_output.log ---"
    tail -50 /root/10-23-bot/ds/qwen_output.log
else
    echo "❌ 未找到 qwen_output.log"
fi
echo ""

echo "=== 4. 检查 Supervisor 日志 ==="
if [ -f "/var/log/supervisor/qwen-stderr---supervisor-*.log" ]; then
    echo "--- Supervisor stderr ---"
    tail -30 /var/log/supervisor/qwen-stderr---supervisor-*.log 2>/dev/null | head -30
fi

if [ -f "/var/log/supervisor/qwen-stdout---supervisor-*.log" ]; then
    echo "--- Supervisor stdout ---"
    tail -30 /var/log/supervisor/qwen-stdout---supervisor-*.log 2>/dev/null | head -30
fi
echo ""

echo "=== 5. 尝试手动启动 Qwen（看详细错误）==="
echo "正在尝试手动启动..."
cd /root/10-23-bot/ds
timeout 10 python3 qwen_多币种智能版.py 2>&1 | head -100 &
MANUAL_PID=$!

sleep 5

if kill -0 $MANUAL_PID 2>/dev/null; then
    echo "✅ Qwen 手动启动成功，正在运行中"
    kill $MANUAL_PID 2>/dev/null
else
    echo "❌ Qwen 手动启动也失败了"
fi
echo ""

echo "=== 6. 检查 Python 依赖 ==="
python3 -c "
try:
    import ccxt
    print('✅ ccxt 已安装')
except:
    print('❌ ccxt 未安装')

try:
    import openai
    print('✅ openai 已安装')
except:
    print('❌ openai 未安装')

try:
    import schedule
    print('✅ schedule 已安装')
except:
    print('❌ schedule 未安装')

try:
    import pandas
    print('✅ pandas 已安装')
except:
    print('❌ pandas 未安装')
"
echo ""

echo "=== 7. 检查环境变量文件 ==="
if [ -f "/root/10-23-bot/ds/.env.qwen" ]; then
    echo "✅ .env.qwen 存在"
    echo "文件大小: $(wc -c < /root/10-23-bot/ds/.env.qwen) 字节"
    echo ""
    echo "--- 环境变量（隐藏敏感信息）---"
    cat /root/10-23-bot/ds/.env.qwen | grep -v "API_KEY\|SECRET" | head -20
else
    echo "❌ .env.qwen 不存在"
fi
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
