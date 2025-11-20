#!/bin/bash
# 快速修复API 500错误

set -e

echo "========================================"
echo "🚑 快速修复API 500错误"
echo "========================================"
echo ""

cd "$(dirname "$0")"

echo "【诊断】检查问题..."
echo ""

# 检查qwen最后一条订单
echo "1️⃣ qwen最后一条订单:"
tail -1 trading_data/qwen/trades_history.csv | head -c 200
echo "..."
echo ""

# 检查deepseek最后一条订单
echo "2️⃣ deepseek最后一条订单:"
tail -1 trading_data/deepseek/trades_history.csv | head -c 200
echo "..."
echo ""

echo "========================================"
echo "📋 修复方案:"
echo "========================================"
echo ""
echo "【方案A】从备份恢复CSV，只保留总资产修正（推荐）"
echo "【方案B】查看详细错误信息"
echo "【方案C】手动检查和修正"
echo ""
read -p "请选择 [A/B/C]: " choice

case $choice in
    [Aa])
        echo ""
        echo "执行方案A: 从备份恢复CSV..."
        
        # 检查备份是否存在
        BACKUP_DIR=$(ls -td data_backup/*/ 2>/dev/null | head -1)
        if [ -z "$BACKUP_DIR" ]; then
            echo "❌ 未找到备份目录"
            exit 1
        fi
        
        echo "使用备份: $BACKUP_DIR"
        
        # 恢复qwen的trades_history.csv
        if [ -f "${BACKUP_DIR}trades_history.csv" ]; then
            # 先备份当前的（以防万一）
            cp trading_data/qwen/trades_history.csv trading_data/qwen/trades_history.csv.before_restore
            
            # 从备份恢复
            cp "${BACKUP_DIR}trades_history.csv" trading_data/qwen/
            echo "✅ 已恢复 qwen/trades_history.csv"
        fi
        
        # 只修正总资产
        echo ""
        echo "修正总资产..."
        python3 << 'PYTHON_EOF'
import json

# 修正qwen总资产
try:
    with open('trading_data/qwen/system_status.json', 'r', encoding='utf-8') as f:
        status = json.load(f)
    
    status['总资产'] = 107.56
    status['total_assets'] = 107.56
    
    with open('trading_data/qwen/system_status.json', 'w', encoding='utf-8') as f:
        json.dump(status, f, ensure_ascii=False, indent=2)
    
    print("✅ qwen总资产已更新为 107.56 U")
except Exception as e:
    print(f"❌ qwen修正失败: {e}")

# 修正deepseek总资产
try:
    with open('trading_data/deepseek/system_status.json', 'r', encoding='utf-8') as f:
        status = json.load(f)
    
    status['总资产'] = 101.93
    status['total_assets'] = 101.93
    
    with open('trading_data/deepseek/system_status.json', 'w', encoding='utf-8') as f:
        json.dump(status, f, ensure_ascii=False, indent=2)
    
    print("✅ deepseek总资产已更新为 101.93 U")
except Exception as e:
    print(f"❌ deepseek修正失败: {e}")
PYTHON_EOF
        
        echo ""
        echo "✅ 修复完成！"
        echo ""
        echo "💡 下一步:"
        echo "   1. 重启后端服务"
        echo "   2. 刷新前端页面"
        echo "   3. 检查是否正常显示"
        ;;
    
    [Bb])
        echo ""
        echo "执行方案B: 查看详细错误..."
        echo ""
        
        python3 << 'PYTHON_EOF'
import csv
import json
import traceback

for model in ['qwen', 'deepseek']:
    print(f"\n{'='*50}")
    print(f"检查 {model}")
    print('='*50)
    
    data_dir = f'trading_data/{model}'
    
    try:
        # 读取trades_history.csv
        with open(f'{data_dir}/trades_history.csv', 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            trades = list(reader)
        
        print(f"✅ 读取 {len(trades)} 条交易记录")
        
        # 检查最后一条
        if trades:
            last_trade = trades[-1]
            print(f"\n最后一条记录 (前5个字段):")
            for i, (key, value) in enumerate(last_trade.items()):
                if i < 5:
                    print(f"  {key}: {value!r}")
            
            # 检查关键字段
            print(f"\n关键字段检查:")
            for field in ['币种', '方向', '开仓价格', '数量', '杠杆', '盈亏(U)']:
                value = last_trade.get(field, '')
                print(f"  {field}: {value!r} (长度: {len(str(value))})")
            
            # 尝试数值转换
            try:
                pnl_str = last_trade.get('盈亏(U)', '0')
                if pnl_str and pnl_str.strip():
                    pnl = float(pnl_str)
                    print(f"\n✅ 盈亏可转换: {pnl}")
                else:
                    print(f"\n✅ 盈亏为空（正常）")
            except Exception as e:
                print(f"\n❌ 盈亏转换失败: {e}")
        
        # 读取system_status.json
        with open(f'{data_dir}/system_status.json', 'r', encoding='utf-8') as f:
            status = json.load(f)
        
        print(f"\n✅ system_status.json:")
        print(f"  总资产: {status.get('总资产', status.get('total_assets'))}")
        print(f"  持仓数: {len(status.get('持仓详情', []))}")
        
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        traceback.print_exc()
PYTHON_EOF
        
        echo ""
        echo "💡 检查完成，请查看上方输出"
        ;;
    
    [Cc])
        echo ""
        echo "执行方案C: 手动检查..."
        echo ""
        echo "qwen trades_history.csv 最后3行:"
        tail -3 trading_data/qwen/trades_history.csv
        echo ""
        echo "deepseek trades_history.csv 最后3行:"
        tail -3 trading_data/deepseek/trades_history.csv
        echo ""
        echo "💡 请手动编辑文件修正问题"
        ;;
    
    *)
        echo "❌ 无效选项"
        exit 1
        ;;
esac

echo ""
echo "========================================"

