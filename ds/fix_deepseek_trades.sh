#!/bin/bash
# 修复deepseek的trades_history.csv格式问题

set -e

echo "=========================================="
echo "🔧 修复 DeepSeek trades_history.csv"
echo "=========================================="
echo ""

cd "$(dirname "$0")"

# 1. 先运行诊断
echo "【步骤1】诊断问题..."
python3 check_trades_format.py

echo ""
echo "=========================================="
echo "📋 修复选项"
echo "=========================================="
echo ""
echo "请选择修复方式:"
echo "  1) 从最近的备份恢复 (推荐)"
echo "  2) 删除最后1行 (恢复的问题记录)"
echo "  3) 删除最后N行 (手动指定)"
echo "  4) 删除所有未平仓记录并从币安API重新恢复"
echo "  5) 手动检查，不自动修复"
echo ""
read -p "请选择 [1-5]: " choice

case $choice in
    1)
        echo ""
        echo "【从备份恢复】"
        
        # 查找最新的备份
        BACKUP_DIR=$(ls -td data_backup/*/ 2>/dev/null | head -1)
        
        if [ -z "$BACKUP_DIR" ]; then
            echo "❌ 未找到备份目录"
            exit 1
        fi
        
        echo "使用备份: $BACKUP_DIR"
        
        # 检查备份中是否有deepseek的文件
        if [ -f "${BACKUP_DIR}deepseek_trades_history.csv" ]; then
            BACKUP_FILE="${BACKUP_DIR}deepseek_trades_history.csv"
        elif [ -f "${BACKUP_DIR}trades_history.csv" ]; then
            BACKUP_FILE="${BACKUP_DIR}trades_history.csv"
        else
            echo "❌ 备份中未找到 trades_history.csv"
            exit 1
        fi
        
        # 先备份当前文件
        cp trading_data/deepseek/trades_history.csv trading_data/deepseek/trades_history.csv.before_fix
        
        # 恢复
        cp "$BACKUP_FILE" trading_data/deepseek/trades_history.csv
        
        echo "✅ 已从备份恢复"
        echo "   当前文件已备份为: trades_history.csv.before_fix"
        ;;
    
    2)
        echo ""
        echo "【删除最后1行】"
        
        # 备份
        cp trading_data/deepseek/trades_history.csv trading_data/deepseek/trades_history.csv.before_fix
        
        # 删除最后一行
        head -n -1 trading_data/deepseek/trades_history.csv > /tmp/trades_temp.csv
        mv /tmp/trades_temp.csv trading_data/deepseek/trades_history.csv
        
        echo "✅ 已删除最后1行"
        ;;
    
    3)
        echo ""
        read -p "要删除最后几行? " n
        
        if ! [[ "$n" =~ ^[0-9]+$ ]]; then
            echo "❌ 无效的数字"
            exit 1
        fi
        
        echo "【删除最后${n}行】"
        
        # 备份
        cp trading_data/deepseek/trades_history.csv trading_data/deepseek/trades_history.csv.before_fix
        
        # 删除最后N行
        head -n -${n} trading_data/deepseek/trades_history.csv > /tmp/trades_temp.csv
        mv /tmp/trades_temp.csv trading_data/deepseek/trades_history.csv
        
        echo "✅ 已删除最后${n}行"
        ;;
    
    4)
        echo ""
        echo "【清理并重新从币安恢复】"
        
        # 备份
        cp trading_data/deepseek/trades_history.csv trading_data/deepseek/trades_history.csv.before_fix
        
        # 删除所有未平仓记录
        python3 << 'EOF'
import csv
from pathlib import Path

trades_file = Path("trading_data/deepseek/trades_history.csv")

# 读取所有记录
with open(trades_file, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    fieldnames = reader.fieldnames
    trades = list(reader)

# 只保留已平仓的
closed_trades = [t for t in trades if t.get('平仓时间', '').strip()]

print(f"原始记录: {len(trades)}")
print(f"已平仓: {len(closed_trades)}")
print(f"删除未平仓: {len(trades) - len(closed_trades)}")

# 写回
with open(trades_file, 'w', encoding='utf-8', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(closed_trades)

print("✅ 已清理未平仓记录")
EOF
        
        echo ""
        echo "现在运行恢复工具重新添加持仓记录..."
        echo "   python3 restore_from_binance_papi.py"
        echo ""
        read -p "立即运行? (y/n): " run_restore
        
        if [ "$run_restore" = "y" ]; then
            python3 restore_from_binance_papi.py
        fi
        ;;
    
    5)
        echo ""
        echo "【手动检查模式】"
        echo ""
        echo "手动检查命令:"
        echo "  # 查看最后5行"
        echo "  tail -5 trading_data/deepseek/trades_history.csv"
        echo ""
        echo "  # 查看字段数"
        echo "  head -1 trading_data/deepseek/trades_history.csv | awk -F',' '{print NF}'"
        echo "  tail -1 trading_data/deepseek/trades_history.csv | awk -F',' '{print NF}'"
        echo ""
        echo "  # 手动编辑"
        echo "  vim trading_data/deepseek/trades_history.csv"
        exit 0
        ;;
    
    *)
        echo "❌ 无效选项"
        exit 1
        ;;
esac

# 验证修复结果
echo ""
echo "=========================================="
echo "🔍 验证修复结果"
echo "=========================================="
echo ""

python3 << 'EOF'
import csv
from pathlib import Path

trades_file = Path("trading_data/deepseek/trades_history.csv")

with open(trades_file, 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    fieldnames = reader.fieldnames
    trades = list(reader)

print(f"✓ 总记录数: {len(trades)}")
print(f"✓ 字段数: {len(fieldnames)}")

# 检查最后一条
if trades:
    last = trades[-1]
    print(f"✓ 最后一条: {last.get('币种', 'N/A')} {last.get('方向', 'N/A')} {last.get('开仓时间', 'N/A')}")
    
    # 检查字段数
    if len(last) != len(fieldnames):
        print(f"⚠️  最后一条字段数不匹配: {len(last)} != {len(fieldnames)}")
    else:
        print(f"✓ 字段数匹配")

# 统计未平仓
open_count = sum(1 for t in trades if not t.get('平仓时间', '').strip())
print(f"✓ 未平仓订单: {open_count}")
EOF

echo ""
echo "=========================================="
echo "✅ 修复完成"
echo "=========================================="
echo ""
echo "💡 下一步:"
echo "   1. 重启后端: cd /root/10-23-bot && killall python3 && nohup python3 每日壁纸更换.py > nohup.out 2>&1 &"
echo "   2. 检查前端是否正常显示"
echo "   3. 如有问题，从备份恢复: cp trading_data/deepseek/trades_history.csv.before_fix trading_data/deepseek/trades_history.csv"
echo ""

