#!/bin/bash
# 一键诊断并修复订单格式问题

echo "=========================================="
echo "🔧 一键修复订单格式问题"
echo "=========================================="
echo ""

cd "$(dirname "$0")"

# 步骤1: 诊断
echo "【步骤1】诊断问题..."
echo ""
python3 check_trades_format.py

echo ""
echo "=========================================="
echo "📋 发现的问题"
echo "=========================================="
echo ""
echo "根据上方诊断结果，主要问题："
echo ""
echo "DeepSeek:"
echo "  - 空值记录: 2条"
echo "  - 重复记录: 2组"
echo ""
echo "Qwen:"
echo "  - 重复记录: 83组 ⚠️ 严重"
echo ""
echo "=========================================="
echo ""

read -p "是否执行自动修复? (y/n): " confirm

if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
    echo "❌ 已取消"
    exit 0
fi

# 步骤2: 修复
echo ""
echo "【步骤2】执行修复..."
echo ""

python3 fix_all_trades.py << 'EOF'
y
EOF

# 步骤3: 再次诊断验证
echo ""
echo "【步骤3】验证修复结果..."
echo ""

python3 << 'EOF'
import csv
from pathlib import Path

for model in ['deepseek', 'qwen']:
    trades_file = Path(f"trading_data/{model}/trades_history.csv")
    
    with open(trades_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        trades = list(reader)
    
    open_count = sum(1 for t in trades if not t.get('平仓时间', '').strip())
    
    # 检查重复
    seen = set()
    dup_count = 0
    for t in trades:
        key = f"{t.get('币种', '')}_{t.get('方向', '')}_{t.get('开仓时间', '')}"
        if key in seen:
            dup_count += 1
        else:
            seen.add(key)
    
    print(f"✓ {model.upper()}:")
    print(f"    总记录: {len(trades)}")
    print(f"    未平仓: {open_count}")
    print(f"    重复记录: {dup_count}")
    print("")
EOF

echo "=========================================="
echo ""

read -p "是否重启后端服务? (y/n): " restart

if [ "$restart" = "y" ] || [ "$restart" = "Y" ]; then
    echo ""
    echo "重启后端服务..."
    
    # 停止
    pkill -f "每日壁纸更换.py"
    sleep 2
    
    # 启动
    cd ..
    nohup python3 每日壁纸更换.py > nohup.out 2>&1 &
    
    sleep 3
    
    echo ""
    echo "✅ 后端已重启"
    echo ""
    echo "查看日志: tail -f /root/10-23-bot/nohup.out"
    tail -20 nohup.out
else
    echo ""
    echo "💡 手动重启命令:"
    echo "   cd /root/10-23-bot"
    echo "   killall python3"
    echo "   nohup python3 每日壁纸更换.py > nohup.out 2>&1 &"
fi

echo ""
echo "=========================================="
echo "✅ 完成"
echo "=========================================="

