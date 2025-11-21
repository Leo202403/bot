#!/bin/bash
# 重启后端服务

echo "=========================================="
echo "🔄 重启后端服务"
echo "=========================================="
echo ""

# 后端项目路径
BACKEND_DIR="/root/pythonc程序/my_project"

# 1. 停止现有进程
echo "【步骤1】停止现有进程..."

if ps aux | grep "[每]日壁纸更换.py" > /dev/null; then
    echo "  正在停止..."
    pkill -f "每日壁纸更换.py"
    
    # 等待进程完全停止
    sleep 3
    
    # 确认停止
    if ps aux | grep "[每]日壁纸更换.py" > /dev/null; then
        echo "  ⚠️  进程仍在运行，强制终止..."
        pkill -9 -f "每日壁纸更换.py"
        sleep 2
    fi
    
    echo "  ✓ 已停止"
else
    echo "  ℹ️  进程未运行"
fi

echo ""

# 2. 启动后端
echo "【步骤2】启动后端..."
echo "  工作目录: $BACKEND_DIR"
echo ""

cd "$BACKEND_DIR"

# 备份旧日志
if [ -f "nohup.out" ]; then
    mv nohup.out "nohup.out.backup_$(date +%Y%m%d_%H%M%S)"
    echo "  ✓ 已备份旧日志"
fi

# 启动
nohup python3 每日壁纸更换.py > nohup.out 2>&1 &

echo "  ✓ 已启动 (PID: $!)"
echo ""

# 3. 等待启动
echo "【步骤3】等待启动..."
sleep 5

# 4. 检查进程
if ps aux | grep "[每]日壁纸更换.py" > /dev/null; then
    echo "  ✓ 进程运行正常"
    echo ""
    ps aux | grep "[每]日壁纸更换.py" | grep -v grep
else
    echo "  ❌ 进程启动失败！"
    echo ""
    echo "查看日志:"
    tail -20 "$BACKEND_DIR/nohup.out"
    exit 1
fi

echo ""

# 5. 查看启动日志
echo "【步骤4】启动日志（最后20行）..."
echo "----------------------------------------"
tail -20 "$BACKEND_DIR/nohup.out"
echo "----------------------------------------"

echo ""

# 6. 测试API
echo "【步骤5】测试API..."
sleep 3

if curl -s http://localhost:5000/trading-summary?model=deepseek&range=week | grep -q "status"; then
    echo "  ✓ DeepSeek API 正常"
else
    echo "  ⚠️  DeepSeek API 可能有问题"
fi

if curl -s http://localhost:5000/trading-summary?model=qwen&range=week | grep -q "status"; then
    echo "  ✓ Qwen API 正常"
else
    echo "  ⚠️  Qwen API 可能有问题"
fi

echo ""
echo "=========================================="
echo "✅ 重启完成"
echo "=========================================="
echo ""
echo "💡 后续操作:"
echo "  1. 查看实时日志: tail -f $BACKEND_DIR/nohup.out"
echo "  2. 测试API: cd /root/10-23-bot/ds && ./test_api.sh"
echo "  3. 刷新前端页面"
echo ""

