#!/bin/bash
# 测试后端API是否正常

echo "=========================================="
echo "🧪 测试后端API"
echo "=========================================="
echo ""

# 后端项目路径
BACKEND_DIR="/root/pythonc程序/my_project"

# 1. 检查后端进程
echo "【步骤1】检查后端进程..."
echo ""

# 检测方法1: 通过端口检查（最可靠）
if netstat -tlnp 2>/dev/null | grep ":5001" | grep -q "LISTEN" || \
   ss -tlnp 2>/dev/null | grep ":5001" | grep -q "LISTEN"; then
    echo "✓ 后端服务运行中（监听端口5001）"
    
    # 尝试显示进程信息
    if ps aux | grep -E "python.*my_project" | grep -v grep > /dev/null; then
        echo "  进程信息:"
        ps aux | grep -E "python.*my_project" | grep -v grep | head -3
    fi
elif pgrep -f "$BACKEND_DIR" > /dev/null; then
    echo "✓ 后端进程运行中"
    echo "  PID(s): $(pgrep -f "$BACKEND_DIR" | tr '\n' ' ')"
else
    echo "❌ 后端进程未运行！"
    echo ""
    echo "启动命令:"
    echo "  cd $BACKEND_DIR"
    echo "  nohup python3 每日壁纸更换.py > nohup.out 2>&1 &"
    exit 1
fi

echo ""
echo "【步骤2】测试API端点..."
echo ""

# 2. 测试DeepSeek API
echo "2.1 测试 DeepSeek API:"
echo "    URL: http://localhost:5001/trading-summary?model=deepseek&range=week"
echo ""

# 使用 curl 测试，添加超时和重试机制
RESPONSE=$(curl -s -o /tmp/deepseek_response.json -w "%{http_code}" \
    --max-time 10 \
    --connect-timeout 5 \
    http://localhost:5001/trading-summary?model=deepseek\&range=week 2>&1)

# 检查 curl 是否成功执行
if [ $? -ne 0 ]; then
    echo "    ❌ 请求失败: curl命令执行出错"
    echo "    错误信息: $RESPONSE"
    RESPONSE="000"
fi

if [ "$RESPONSE" = "200" ]; then
    echo "    ✓ 状态码: 200 OK"
    
    # 检查返回内容
    if grep -q "status" /tmp/deepseek_response.json; then
        echo "    ✓ 返回了JSON数据"
        
        # 显示关键信息
        python3 << 'EOF'
import json

with open('/tmp/deepseek_response.json', 'r') as f:
    data = json.load(f)

status = data.get('status', {})
positions = data.get('positions', [])

print(f"    ✓ 总资产: {status.get('total_assets', 0)} USDT")
print(f"    ✓ 持仓数: {len(positions)}")
print(f"    ✓ 已实现盈亏: {status.get('total_realized_pnl', 0)} USDT")
EOF
    else
        echo "    ⚠️  返回了数据但格式可能不正确"
        head -c 200 /tmp/deepseek_response.json
    fi
else
    echo "    ❌ 状态码: $RESPONSE (错误)"
    echo "    响应内容:"
    cat /tmp/deepseek_response.json
fi

echo ""

# 3. 测试Qwen API
echo "2.2 测试 Qwen API:"
echo "    URL: http://localhost:5001/trading-summary?model=qwen&range=week"
echo ""

# 使用 curl 测试，添加超时和重试机制
RESPONSE=$(curl -s -o /tmp/qwen_response.json -w "%{http_code}" \
    --max-time 10 \
    --connect-timeout 5 \
    http://localhost:5001/trading-summary?model=qwen\&range=week 2>&1)

# 检查 curl 是否成功执行
if [ $? -ne 0 ]; then
    echo "    ❌ 请求失败: curl命令执行出错"
    echo "    错误信息: $RESPONSE"
    RESPONSE="000"
fi

if [ "$RESPONSE" = "200" ]; then
    echo "    ✓ 状态码: 200 OK"
    
    if grep -q "status" /tmp/qwen_response.json; then
        echo "    ✓ 返回了JSON数据"
        
        python3 << 'EOF'
import json

with open('/tmp/qwen_response.json', 'r') as f:
    data = json.load(f)

status = data.get('status', {})
positions = data.get('positions', [])

print(f"    ✓ 总资产: {status.get('total_assets', 0)} USDT")
print(f"    ✓ 持仓数: {len(positions)}")
print(f"    ✓ 已实现盈亏: {status.get('total_realized_pnl', 0)} USDT")
EOF
    else
        echo "    ⚠️  返回了数据但格式可能不正确"
        head -c 200 /tmp/qwen_response.json
    fi
else
    echo "    ❌ 状态码: $RESPONSE (错误)"
    echo "    响应内容:"
    cat /tmp/qwen_response.json
fi

echo ""
echo "【步骤3】检查后端日志..."
echo ""

LOG_FILE="$BACKEND_DIR/nohup.out"

if [ -f "$LOG_FILE" ]; then
    echo "日志文件: $LOG_FILE"
    echo "最后20行日志:"
    echo "----------------------------------------"
    tail -20 "$LOG_FILE"
    echo "----------------------------------------"
    
    # 检查错误
    if tail -50 "$LOG_FILE" | grep -i "error\|exception\|traceback" > /dev/null; then
        echo ""
        echo "⚠️  发现错误信息:"
        tail -50 "$LOG_FILE" | grep -i -A 3 "error\|exception"
    fi
else
    echo "❌ 未找到日志文件: $LOG_FILE"
fi

echo ""
echo "=========================================="
echo "📊 测试总结"
echo "=========================================="
echo ""

# 生成测试报告
python3 << 'EOF'
import json
import os

results = {}

# 检查DeepSeek
if os.path.exists('/tmp/deepseek_response.json'):
    try:
        with open('/tmp/deepseek_response.json', 'r') as f:
            data = json.load(f)
            if 'status' in data:
                results['deepseek'] = 'OK'
            else:
                results['deepseek'] = 'FORMAT_ERROR'
    except:
        results['deepseek'] = 'ERROR'
else:
    results['deepseek'] = 'NO_RESPONSE'

# 检查Qwen
if os.path.exists('/tmp/qwen_response.json'):
    try:
        with open('/tmp/qwen_response.json', 'r') as f:
            data = json.load(f)
            if 'status' in data:
                results['qwen'] = 'OK'
            else:
                results['qwen'] = 'FORMAT_ERROR'
    except:
        results['qwen'] = 'ERROR'
else:
    results['qwen'] = 'NO_RESPONSE'

print("API状态:")
print(f"  DeepSeek: {results['deepseek']}")
print(f"  Qwen: {results['qwen']}")
print("")

if results['deepseek'] == 'OK' and results['qwen'] == 'OK':
    print("✅ 所有API正常")
    print("")
    print("如果前端仍不显示，可能是:")
    print("  1. 浏览器缓存问题 → 硬刷新 (Ctrl+Shift+R)")
    print("  2. 前端JavaScript错误 → 检查浏览器控制台")
    print("  3. 跨域问题 → 检查浏览器Network标签")
else:
    print("❌ 发现问题")
    print("")
    print("建议操作:")
    if results['deepseek'] != 'OK':
        print("  1. 检查 trading_data/deepseek/ 目录权限")
        print("  2. 检查 system_status.json 是否存在且格式正确")
    if results['qwen'] != 'OK':
        print("  1. 检查 trading_data/qwen/ 目录权限")
        print("  2. 检查 system_status.json 是否存在且格式正确")
    print(f"  3. 查看完整日志: tail -100 {os.getenv('BACKEND_DIR', '/root/pythonc程序/my_project')}/nohup.out")
    print("  4. 重启后端服务")
EOF

echo ""
echo "=========================================="

