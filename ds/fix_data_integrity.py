#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据完整性修正工具
解决问题：
1. 总资产数量计算错误
2. 订单记录丢失
"""

import json
import csv
import os
from pathlib import Path
from datetime import datetime
import shutil


def backup_files(model_name):
    """备份原始文件"""
    data_dir = Path(__file__).parent / "trading_data" / model_name
    backup_dir = Path(__file__).parent / "data_backup" / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    
    files_to_backup = [
        'system_status.json',
        'trades_history.csv',
        'current_positions.csv',
        'pnl_history.csv'
    ]
    
    print(f"\n📦 备份 {model_name} 数据...")
    for filename in files_to_backup:
        src = data_dir / filename
        if src.exists():
            dst = backup_dir / filename
            shutil.copy2(src, dst)
            print(f"   ✓ {filename}")
    
    print(f"✅ 备份完成: {backup_dir}")
    return backup_dir


def recalculate_total_assets(model_name):
    """重新计算总资产"""
    data_dir = Path(__file__).parent / "trading_data" / model_name
    status_file = data_dir / "system_status.json"
    positions_file = data_dir / "current_positions.csv"
    
    if not status_file.exists():
        print(f"⚠️  {model_name}: system_status.json 不存在")
        return None
    
    # 读取当前状态
    with open(status_file, 'r', encoding='utf-8') as f:
        status = json.load(f)
    
    # 初始资金
    initial_capital = 100.0
    
    # 1. 计算已实现盈亏（从trades_history.csv）
    trades_file = data_dir / "trades_history.csv"
    realized_pnl = 0.0
    closed_trades_count = 0
    
    if trades_file.exists():
        with open(trades_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for trade in reader:
                close_time = trade.get('平仓时间', '').strip()
                if close_time:  # 已平仓
                    pnl_str = trade.get('盈亏(U)', '0')
                    try:
                        pnl = float(pnl_str)
                        realized_pnl += pnl
                        closed_trades_count += 1
                    except (ValueError, TypeError):
                        pass
    
    # 2. 计算未实现盈亏（从current_positions.csv或system_status.json）
    unrealized_pnl = 0.0
    position_count = 0
    
    # 优先从system_status.json读取
    if '持仓详情' in status and isinstance(status['持仓详情'], list):
        for pos in status['持仓详情']:
            unrealized_pnl += pos.get('盈亏', 0)
            position_count += 1
    elif positions_file.exists():
        with open(positions_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for pos in reader:
                pnl_str = pos.get('盈亏', pos.get('unrealized_pnl', '0'))
                try:
                    unrealized_pnl += float(pnl_str)
                    position_count += 1
                except (ValueError, TypeError):
                    pass
    
    # 3. 计算正确的总资产
    correct_total_assets = initial_capital + realized_pnl + unrealized_pnl
    
    # 获取当前记录的总资产
    old_total_assets = status.get('总资产', status.get('total_assets', 0))
    
    print(f"\n📊 {model_name} 资产核算:")
    print(f"   初始资金: {initial_capital:.2f} U")
    print(f"   已实现盈亏: {realized_pnl:.2f} U ({closed_trades_count} 笔)")
    print(f"   未实现盈亏: {unrealized_pnl:.2f} U ({position_count} 持仓)")
    print(f"   ---")
    print(f"   旧记录总资产: {old_total_assets:.2f} U")
    print(f"   正确总资产: {correct_total_assets:.2f} U")
    print(f"   差异: {correct_total_assets - old_total_assets:.2f} U")
    
    return {
        'model': model_name,
        'initial_capital': initial_capital,
        'realized_pnl': realized_pnl,
        'unrealized_pnl': unrealized_pnl,
        'correct_total_assets': correct_total_assets,
        'old_total_assets': old_total_assets,
        'difference': correct_total_assets - old_total_assets,
        'closed_trades_count': closed_trades_count,
        'position_count': position_count
    }


def fix_total_assets(model_name, correct_value):
    """修正system_status.json中的总资产"""
    data_dir = Path(__file__).parent / "trading_data" / model_name
    status_file = data_dir / "system_status.json"
    
    with open(status_file, 'r', encoding='utf-8') as f:
        status = json.load(f)
    
    # 更新总资产
    status['总资产'] = correct_value
    status['total_assets'] = correct_value
    
    # 保存
    with open(status_file, 'w', encoding='utf-8') as f:
        json.dump(status, f, ensure_ascii=False, indent=2)
    
    print(f"✅ {model_name}: 总资产已更新为 {correct_value:.2f} U")


def check_missing_trades(model_name):
    """检查订单记录完整性"""
    data_dir = Path(__file__).parent / "trading_data" / model_name
    trades_file = data_dir / "trades_history.csv"
    positions_file = data_dir / "current_positions.csv"
    status_file = data_dir / "system_status.json"
    
    print(f"\n🔍 {model_name} 订单完整性检查:")
    
    # 1. 检查trades_history.csv是否存在
    if not trades_file.exists():
        print("   ⚠️  trades_history.csv 不存在!")
        return
    
    # 2. 读取所有订单
    all_trades = []
    with open(trades_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        all_trades = list(reader)
    
    # 3. 统计
    open_trades = [t for t in all_trades if not t.get('平仓时间', '').strip()]
    closed_trades = [t for t in all_trades if t.get('平仓时间', '').strip()]
    
    print(f"   总订单数: {len(all_trades)}")
    print(f"   未平仓: {len(open_trades)}")
    print(f"   已平仓: {len(closed_trades)}")
    
    # 4. 检查持仓是否一致
    if status_file.exists():
        with open(status_file, 'r', encoding='utf-8') as f:
            status = json.load(f)
        
        status_positions = status.get('持仓详情', [])
        print(f"   system_status.json 持仓数: {len(status_positions)}")
        
        if len(open_trades) != len(status_positions):
            print(f"   ⚠️  不一致! trades_history未平仓({len(open_trades)}) != status持仓({len(status_positions)})")
            
            # 列出差异
            trades_symbols = set(f"{t.get('币种', '')}_{t.get('方向', '')}" for t in open_trades)
            status_symbols = set(f"{p.get('币种', '')}_{p.get('方向', '')}" for p in status_positions)
            
            missing_in_trades = status_symbols - trades_symbols
            missing_in_status = trades_symbols - status_symbols
            
            if missing_in_trades:
                print(f"   ❌ trades_history.csv缺失的订单: {missing_in_trades}")
            if missing_in_status:
                print(f"   ❌ system_status.json缺失的持仓: {missing_in_status}")
        else:
            print("   ✓ 持仓记录一致")
    
    # 5. 检查订单编号连续性
    order_ids = []
    for trade in all_trades:
        order_id = trade.get('订单编号', '').strip()
        if order_id:
            try:
                # 假设订单编号格式类似: deepseek_BTC_20251120_001
                parts = order_id.split('_')
                if len(parts) >= 4:
                    seq_num = int(parts[-1])
                    order_ids.append(seq_num)
            except (ValueError, IndexError):
                pass
    
    if order_ids:
        order_ids.sort()
        missing_ids = []
        for i in range(order_ids[0], order_ids[-1] + 1):
            if i not in order_ids:
                missing_ids.append(i)
        
        if missing_ids:
            print(f"   ⚠️  订单编号缺失: {missing_ids[:10]}{'...' if len(missing_ids) > 10 else ''}")
        else:
            print(f"   ✓ 订单编号连续 ({order_ids[0]}-{order_ids[-1]})")


def restore_missing_trades_from_positions(model_name):
    """从current_positions.csv恢复缺失的订单记录"""
    data_dir = Path(__file__).parent / "trading_data" / model_name
    trades_file = data_dir / "trades_history.csv"
    status_file = data_dir / "system_status.json"
    
    if not status_file.exists():
        print(f"⚠️  {model_name}: system_status.json 不存在")
        return
    
    # 读取当前持仓
    with open(status_file, 'r', encoding='utf-8') as f:
        status = json.load(f)
    
    positions = status.get('持仓详情', [])
    if not positions:
        print(f"✓ {model_name}: 无持仓，无需恢复")
        return
    
    # 读取现有订单
    existing_trades = []
    if trades_file.exists():
        with open(trades_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            existing_trades = list(reader)
    
    # 获取字段名
    if existing_trades:
        fieldnames = list(existing_trades[0].keys())
    else:
        fieldnames = ['币种', '方向', '开仓时间', '开仓价格', '数量', '杠杆', 
                     '平仓时间', '平仓价格', '盈亏(U)', '订单编号']
    
    # 检查哪些持仓没有对应的订单记录
    existing_keys = set()
    for trade in existing_trades:
        if not trade.get('平仓时间', '').strip():  # 未平仓
            key = f"{trade.get('币种', '')}_{trade.get('方向', '')}"
            existing_keys.add(key)
    
    # 需要恢复的持仓
    missing_positions = []
    for pos in positions:
        key = f"{pos.get('币种', '')}_{pos.get('方向', '')}"
        if key not in existing_keys:
            missing_positions.append(pos)
    
    if not missing_positions:
        print(f"✓ {model_name}: 所有持仓都有对应订单记录")
        return
    
    print(f"\n🔧 {model_name}: 发现 {len(missing_positions)} 个缺失订单，开始恢复...")
    
    # 恢复订单记录
    recovered_trades = []
    for pos in missing_positions:
        trade_record = {
            '币种': pos.get('币种', ''),
            '方向': pos.get('方向', ''),
            '开仓时间': pos.get('开仓时间', datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
            '开仓价格': pos.get('开仓价格', 0),
            '数量': pos.get('数量', 0),
            '杠杆': pos.get('杠杆', 1),
            '平仓时间': '',
            '平仓价格': '',
            '盈亏(U)': '',
            '订单编号': pos.get('订单编号', f"{model_name}_{pos.get('币种', '')}_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        }
        
        # 补充其他字段
        for field in fieldnames:
            if field not in trade_record:
                trade_record[field] = pos.get(field, '')
        
        recovered_trades.append(trade_record)
        print(f"   ✓ 恢复: {trade_record['币种']} {trade_record['方向']}")
    
    # 追加到trades_history.csv
    with open(trades_file, 'a', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not existing_trades:  # 文件为空，需要写表头
            writer.writeheader()
        writer.writerows(recovered_trades)
    
    print(f"✅ {model_name}: 已恢复 {len(recovered_trades)} 条订单记录")


def main():
    """主函数"""
    import sys
    
    print("=" * 60)
    print("🔧 数据完整性修正工具")
    print("=" * 60)
    
    # 检查命令行参数
    check_only = '--check-only' in sys.argv or '-c' in sys.argv
    
    if check_only:
        print("\n【检查模式】仅检查不修正\n")
    
    models = ['deepseek', 'qwen']
    
    # 步骤1: 备份数据
    if not check_only:
        print("\n【步骤1】备份原始数据")
        for model in models:
            backup_files(model)
    else:
        print("\n【步骤1】跳过备份（检查模式）")
    
    # 步骤2: 检查订单完整性
    print("\n【步骤2】检查订单完整性")
    for model in models:
        check_missing_trades(model)
    
    # 步骤3: 重新计算总资产
    print("\n【步骤3】重新计算总资产")
    results = {}
    for model in models:
        result = recalculate_total_assets(model)
        if result:
            results[model] = result
    
    # 步骤4: 确认是否修正
    print("\n" + "=" * 60)
    print("📋 修正方案:")
    print("=" * 60)
    
    for model, result in results.items():
        if abs(result['difference']) > 0.01:  # 有差异
            print(f"\n{model}:")
            print(f"  当前记录: {result['old_total_assets']:.2f} U")
            print(f"  正确值: {result['correct_total_assets']:.2f} U")
            print(f"  需修正: {result['difference']:+.2f} U")
        else:
            print(f"\n{model}: ✓ 总资产正确，无需修正")
    
    print("\n" + "=" * 60)
    
    if check_only:
        print("\n✅ 检查完成!")
        print("\n💡 提示: 如需修正数据，请运行: python3 fix_data_integrity.py")
        return
    
    choice = input("\n是否执行修正? (y/n): ").strip().lower()
    
    if choice == 'y':
        print("\n【步骤4】执行修正...")
        
        # 修正总资产
        for model, result in results.items():
            if abs(result['difference']) > 0.01:
                fix_total_assets(model, result['correct_total_assets'])
        
        # 恢复缺失订单
        for model in models:
            restore_missing_trades_from_positions(model)
        
        print("\n" + "=" * 60)
        print("✅ 数据修正完成!")
        print("=" * 60)
        print("\n💡 建议:")
        print("   1. 检查修正后的数据是否正确")
        print("   2. 重启交易系统")
        print("   3. 如有问题，可从备份恢复")
    else:
        print("\n❌ 已取消修正")


if __name__ == "__main__":
    main()

