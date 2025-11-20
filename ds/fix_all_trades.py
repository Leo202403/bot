#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
修复所有交易记录问题：
1. 删除空值记录
2. 删除重复记录
3. 验证结果
"""

import csv
from pathlib import Path
from datetime import datetime
import shutil


def fix_trades(model_name):
    """修复指定模型的交易记录"""
    print(f"\n{'='*60}")
    print(f"🔧 修复 {model_name.upper()} 交易记录")
    print(f"{'='*60}")
    
    trades_file = Path(__file__).parent / "trading_data" / model_name / "trades_history.csv"
    
    if not trades_file.exists():
        print(f"❌ 文件不存在: {trades_file}")
        return False
    
    # 备份原文件
    backup_file = trades_file.parent / f"trades_history.csv.backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    shutil.copy2(trades_file, backup_file)
    print(f"✓ 已备份到: {backup_file.name}")
    
    # 读取所有记录
    with open(trades_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = list(reader.fieldnames)
        all_trades = list(reader)
    
    original_count = len(all_trades)
    print(f"✓ 原始记录数: {original_count}")
    
    # 步骤1: 删除空值记录（已平仓但关键字段为空的）
    print("\n【步骤1】删除空值记录...")
    valid_trades = []
    removed_empty = 0
    
    for trade in all_trades:
        # 已平仓的记录必须有这些字段
        is_closed = trade.get('平仓时间', '').strip()
        
        if is_closed:
            # 已平仓订单，检查必需字段
            if (not trade.get('开仓时间', '').strip() or
                not trade.get('币种', '').strip() or
                not trade.get('方向', '').strip()):
                removed_empty += 1
                print(f"  - 删除空值记录: {trade.get('币种', 'N/A')} {trade.get('方向', 'N/A')}")
                continue
        
        valid_trades.append(trade)
    
    print(f"✓ 删除了 {removed_empty} 条空值记录")
    
    # 步骤2: 删除重复记录
    print("\n【步骤2】删除重复记录...")
    seen = {}
    unique_trades = []
    removed_dup = 0
    
    for trade in valid_trades:
        # 生成唯一键：币种_方向_开仓时间
        coin = trade.get('币种', '').strip()
        direction = trade.get('方向', '').strip()
        open_time = trade.get('开仓时间', '').strip()
        
        key = f"{coin}_{direction}_{open_time}"
        
        if key in seen:
            # 重复记录
            removed_dup += 1
            # 如果重复的记录，保留有平仓时间的（已平仓的）
            existing = seen[key]
            existing_closed = existing.get('平仓时间', '').strip()
            current_closed = trade.get('平仓时间', '').strip()
            
            if current_closed and not existing_closed:
                # 当前记录已平仓，替换之前的未平仓记录
                idx = unique_trades.index(existing)
                unique_trades[idx] = trade
                seen[key] = trade
                print(f"  - 替换重复: {coin} {direction} (保留已平仓版本)")
            else:
                print(f"  - 删除重复: {coin} {direction}")
        else:
            seen[key] = trade
            unique_trades.append(trade)
    
    print(f"✓ 删除了 {removed_dup} 条重复记录")
    
    # 步骤3: 统计
    final_count = len(unique_trades)
    open_count = sum(1 for t in unique_trades if not t.get('平仓时间', '').strip())
    closed_count = final_count - open_count
    
    print(f"\n📊 修复后统计:")
    print(f"  原始记录: {original_count}")
    print(f"  删除空值: {removed_empty}")
    print(f"  删除重复: {removed_dup}")
    print(f"  最终记录: {final_count}")
    print(f"    - 已平仓: {closed_count}")
    print(f"    - 未平仓: {open_count}")
    
    # 写回文件
    with open(trades_file, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(unique_trades)
    
    print(f"\n✅ {model_name.upper()} 修复完成")
    return True


def main():
    """主函数"""
    print("="*60)
    print("🔧 批量修复交易记录")
    print("="*60)
    print("\n将修复:")
    print("  1. 删除空值记录（关键字段为空）")
    print("  2. 删除重复记录（同一持仓多次记录）")
    print("  3. 自动备份原文件")
    print("")
    
    confirm = input("确认继续? (y/n): ").strip().lower()
    
    if confirm != 'y':
        print("❌ 已取消")
        return
    
    # 修复两个模型
    success_count = 0
    
    for model in ['deepseek', 'qwen']:
        if fix_trades(model):
            success_count += 1
    
    print("\n" + "="*60)
    print(f"✅ 完成! 成功修复 {success_count}/2 个模型")
    print("="*60)
    
    print("\n💡 下一步:")
    print("  1. 验证修复结果:")
    print("     python3 check_trades_format.py")
    print("")
    print("  2. 重启后端服务:")
    print("     cd /root/10-23-bot")
    print("     killall python3")
    print("     nohup python3 每日壁纸更换.py > nohup.out 2>&1 &")
    print("")
    print("  3. 如有问题，从备份恢复:")
    print("     cd /root/10-23-bot/ds/trading_data/deepseek")
    print("     ls -lt trades_history.csv.backup_*")
    print("     cp trades_history.csv.backup_YYYYMMDD_HHMMSS trades_history.csv")


if __name__ == "__main__":
    main()

