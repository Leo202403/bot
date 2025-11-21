#!/bin/bash
# 修复 DeepSeek trades_history.csv 中的错误记录

echo "=========================================="
echo "🔧 修复 DeepSeek CSV 错误记录"
echo "=========================================="
echo ""

DS_FILE="/root/10-23-bot/ds/trading_data/deepseek/trades_history.csv"

if [ ! -f "$DS_FILE" ]; then
    echo "❌ 文件不存在: $DS_FILE"
    exit 1
fi

# 1. 备份原文件
BACKUP_FILE="${DS_FILE}.before_fix_$(date +%Y%m%d_%H%M%S)"
echo "【步骤1】备份原文件..."
cp "$DS_FILE" "$BACKUP_FILE"
echo "✓ 已备份到: $BACKUP_FILE"
echo ""

# 2. 显示问题记录
echo "【步骤2】检查问题记录..."
echo ""
echo "最后10条记录:"
tail -10 "$DS_FILE"
echo ""

# 3. 删除最后3条错误记录
echo "【步骤3】删除最后3条错误记录..."
head -n -3 "$DS_FILE" > "${DS_FILE}.tmp"
mv "${DS_FILE}.tmp" "$DS_FILE"
echo "✓ 已删除最后3条记录"
echo ""

# 4. 检查修复后的文件
echo "【步骤4】检查修复后的文件..."
echo ""
echo "新的最后5条记录:"
tail -5 "$DS_FILE"
echo ""
echo "总行数: $(wc -l < "$DS_FILE") (包含表头)"
echo "数据行数: $(($(wc -l < "$DS_FILE") - 1))"
echo ""

# 5. 验证所有记录的完整性
echo "【步骤5】验证记录完整性..."
python3 << 'PYEOF'
import csv

try:
    with open('/root/10-23-bot/ds/trading_data/deepseek/trades_history.csv', 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        reader.fieldnames = [name.strip() if name else name for name in reader.fieldnames]
        
        all_trades = []
        incomplete_count = 0
        
        for i, trade in enumerate(reader):
            trade_cleaned = {k.strip() if k else k: v for k, v in trade.items()}
            all_trades.append(trade_cleaned)
            
            # 检查关键字段
            has_open_time = trade_cleaned.get('开仓时间', '').strip()
            has_close_time = trade_cleaned.get('平仓时间', '').strip()
            has_quantity = trade_cleaned.get('数量', '').strip()
            
            # 如果有开仓时间但缺少其他关键字段，视为不完整
            if not has_open_time and not has_close_time:
                incomplete_count += 1
                print(f"⚠️  行 {i+2}: 开仓时间和平仓时间都为空 - {trade_cleaned.get('币种')} {trade_cleaned.get('方向')}")
        
        print(f"\n✓ 总记录数: {len(all_trades)}")
        print(f"✓ 不完整记录: {incomplete_count}")
        
        # 统计已平仓交易
        closed_trades = [t for t in all_trades if t.get('平仓时间', '').strip()]
        print(f"✓ 已平仓交易: {len(closed_trades)}")
        
        # 统计持仓中交易
        open_trades = [t for t in all_trades if t.get('开仓时间', '').strip() and not t.get('平仓时间', '').strip()]
        print(f"✓ 持仓中交易: {len(open_trades)}")
        
except Exception as e:
    print(f"❌ 验证失败: {e}")
    import traceback
    traceback.print_exc()
PYEOF
echo ""

echo "=========================================="
echo "✅ 修复完成！"
echo "=========================================="
echo ""
echo "📝 后续步骤："
echo "  1. 重启后端服务: cd /root/pythonc程序/my_project && ./restart.sh"
echo "  2. 测试 API: cd /root/10-23-bot/ds && ./test_api.sh"
echo "  3. 刷新前端页面查看效果"
echo ""
echo "如果还有问题，可以从备份恢复："
echo "  cp $BACKUP_FILE $DS_FILE"
echo ""

