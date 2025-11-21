#!/bin/bash

# 检查并修复 system_status.json 文件

echo "=========================================="
echo "🔍 检查 system_status.json 文件"
echo "=========================================="
echo ""

DEEPSEEK_STATUS="/root/10-23-bot/ds/trading_data/deepseek/system_status.json"
QWEN_STATUS="/root/10-23-bot/ds/trading_data/qwen/system_status.json"

check_status_file() {
    local file=$1
    local name=$2
    
    echo "【检查 $name】"
    echo "文件路径: $file"
    
    if [ ! -f "$file" ]; then
        echo "❌ 文件不存在！"
        return 1
    fi
    
    echo "✓ 文件存在"
    
    # 检查文件是否为有效的JSON
    if ! python3 -c "import json; json.load(open('$file'))" 2>/dev/null; then
        echo "❌ JSON格式错误！"
        cat "$file"
        return 1
    fi
    
    echo "✓ JSON格式有效"
    
    # 检查必需字段
    python3 << EOF
import json

with open('$file', 'r', encoding='utf-8') as f:
    data = json.load(f)

required_fields = ['total_assets', 'initial_capital', 'total_realized_pnl', 'unrealized_pnl']
missing_fields = []

for field in required_fields:
    if field not in data:
        missing_fields.append(field)

if missing_fields:
    print(f"❌ 缺少字段: {', '.join(missing_fields)}")
    print(f"   当前字段: {list(data.keys())}")
    exit(1)
else:
    print("✓ 所有必需字段都存在")
    print(f"   总资产: {data['total_assets']} USDT")
    print(f"   初始资金: {data['initial_capital']} USDT")
    print(f"   已实现盈亏: {data['total_realized_pnl']} USDT")
    print(f"   未实现盈亏: {data['unrealized_pnl']} USDT")
EOF
    
    echo ""
}

# 检查两个账户
check_status_file "$DEEPSEEK_STATUS" "DeepSeek"
DEEPSEEK_RESULT=$?

check_status_file "$QWEN_STATUS" "Qwen"
QWEN_RESULT=$?

echo "=========================================="
echo "📊 检查结果"
echo "=========================================="

if [ $DEEPSEEK_RESULT -eq 0 ] && [ $QWEN_RESULT -eq 0 ]; then
    echo "✓ 所有配置文件都正常"
else
    echo "❌ 发现问题，需要修复"
    echo ""
    echo "建议操作："
    echo "  1. 从备份恢复: cp backup_*/system_status.json ..."
    echo "  2. 从币安重新恢复数据: ./一键从币安恢复.sh"
fi

echo "=========================================="

