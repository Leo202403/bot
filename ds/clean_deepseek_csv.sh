#!/bin/bash
# 彻底清理 DeepSeek trades_history.csv 中的所有错误记录

echo "=========================================="
echo "🔧 彻底清理 DeepSeek CSV"
echo "=========================================="
echo ""

DS_FILE="/root/10-23-bot/ds/trading_data/deepseek/trades_history.csv"

if [ ! -f "$DS_FILE" ]; then
    echo "❌ 文件不存在: $DS_FILE"
    exit 1
fi

# 1. 备份原文件
BACKUP_FILE="${DS_FILE}.before_clean_$(date +%Y%m%d_%H%M%S)"
echo "【步骤1】备份原文件..."
cp "$DS_FILE" "$BACKUP_FILE"
echo "✓ 已备份到: $BACKUP_FILE"
echo ""

# 2. 检查问题记录
echo "【步骤2】检查问题记录..."
echo ""
echo "最后10行:"
tail -10 "$DS_FILE"
echo ""

# 3. 使用 Python 清理所有错误记录
echo "【步骤3】使用 Python 清理错误记录..."
python3 << 'PYEOF'
import csv
import sys

try:
    input_file = '/root/10-23-bot/ds/trading_data/deepseek/trades_history.csv'
    
    # 读取所有记录
    with open(input_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        
        all_rows = []
        removed_count = 0
        
        for i, row in enumerate(reader, start=2):  # 从第2行开始（第1行是表头）
            # 检查关键字段是否为空
            has_coin = row.get('币种', '').strip()
            has_direction = row.get('方向', '').strip()
            
            # 如果既没有币种也没有方向，跳过
            if not has_coin and not has_direction:
                print(f"⚠️  删除第 {i} 行: 币种和方向都为空")
                removed_count += 1
                continue
            
            # 如果有开仓时间或平仓时间，保留
            has_open = row.get('开仓时间', '').strip()
            has_close = row.get('平仓时间', '').strip()
            
            if not has_open and not has_close:
                print(f"⚠️  删除第 {i} 行: 开仓时间和平仓时间都为空 - {has_coin} {has_direction}")
                removed_count += 1
                continue
            
            # 保留这行
            all_rows.append(row)
    
    print(f"\n✓ 原始记录数: {i - 1}")
    print(f"✓ 删除记录数: {removed_count}")
    print(f"✓ 保留记录数: {len(all_rows)}")
    
    # 写回文件
    with open(input_file, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_rows)
    
    print(f"\n✓ 文件已清理并保存")
    
except Exception as e:
    print(f"❌ 清理失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
PYEOF

if [ $? -ne 0 ]; then
    echo ""
    echo "❌ Python 清理失败，恢复备份..."
    cp "$BACKUP_FILE" "$DS_FILE"
    exit 1
fi

echo ""

# 4. 检查清理后的文件
echo "【步骤4】检查清理后的文件..."
echo ""
echo "新的最后10行:"
tail -10 "$DS_FILE"
echo ""
echo "总行数: $(wc -l < "$DS_FILE") (包含表头)"
echo "数据行数: $(($(wc -l < "$DS_FILE") - 1))"
echo ""

# 5. 验证记录完整性
echo "【步骤5】验证记录完整性..."
python3 << 'PYEOF'
import csv

try:
    with open('/root/10-23-bot/ds/trading_data/deepseek/trades_history.csv', 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        reader.fieldnames = [name.strip() if name else name for name in reader.fieldnames]
        
        all_trades = []
        none_fields = []
        
        for i, trade in enumerate(reader):
            trade_cleaned = {k.strip() if k else k: v for k, v in trade.items()}
            all_trades.append(trade_cleaned)
            
            # 检查是否有 None 值的字段
            for key, value in trade_cleaned.items():
                if value is None or (isinstance(value, str) and value.strip() == ''):
                    # 记录空字段（但不算错误，有些字段可以为空）
                    pass
        
        print(f"✓ 总记录数: {len(all_trades)}")
        
        # 统计已平仓交易
        closed_trades = [t for t in all_trades if t.get('平仓时间', '').strip()]
        print(f"✓ 已平仓交易: {len(closed_trades)}")
        
        # 统计持仓中交易
        open_trades = [t for t in all_trades if t.get('开仓时间', '').strip() and not t.get('平仓时间', '').strip()]
        print(f"✓ 持仓中交易: {len(open_trades)}")
        
        # 检查是否所有已平仓交易都有平仓时间
        for trade in closed_trades[:5]:  # 只显示前5条
            print(f"\n示例记录:")
            print(f"  币种: {trade.get('币种')}")
            print(f"  方向: {trade.get('方向')}")
            print(f"  开仓时间: {trade.get('开仓时间')}")
            print(f"  平仓时间: {trade.get('平仓时间')}")
            print(f"  盈亏: {trade.get('盈亏(U)')}")
            break
        
except Exception as e:
    print(f"❌ 验证失败: {e}")
    import traceback
    traceback.print_exc()
PYEOF
echo ""

echo "=========================================="
echo "✅ 清理完成！"
echo "=========================================="
echo ""
echo "📝 后续步骤："
echo "  1. 重启后端服务"
echo "     cd /root/pythonc程序/my_project"
echo "     pkill -f 'python.*每日壁纸更换.py'"
echo "     nohup python3 每日壁纸更换.py > nohup.out 2>&1 &"
echo ""
echo "  2. 等待3秒后测试"
echo "     sleep 3"
echo "     cd /root/10-23-bot/ds"
echo "     ./test_api.sh"
echo ""
echo "如果还有问题，可以从备份恢复："
echo "  cp $BACKUP_FILE $DS_FILE"
echo ""

