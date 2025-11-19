#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
分析V8.5.2.4.65波动幅度法的退出方式分布和判断准确率
"""

import re
import sys
from collections import defaultdict

def parse_backtest_log(log_file):
    """解析回测日志，提取退出方式统计"""
    
    exit_methods = defaultdict(list)  # {exit_method: [profit1, profit2, ...]}
    
    with open(log_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 正则表达式匹配调试输出
    pattern = r'🔍 调试机会#\d+/\d+: (\w+) (long|short)\s+' \
              r'Entry: ([\d.]+), ATR: ([\d.]+)\s+' \
              r'TP: ([\d.]+)倍, SL: ([\d.]+)倍\s+' \
              r'.*?退出方式: ([^,]+), 退出价: ([\d.]+), 利润: ([-\d.]+)%'
    
    matches = re.findall(pattern, content, re.DOTALL)
    
    print(f"📊 找到 {len(matches)} 条调试记录\n")
    
    for match in matches:
        coin, direction, entry, atr, tp_mult, sl_mult, exit_method, exit_price, profit = match
        exit_method = exit_method.strip()
        profit = float(profit)
        
        exit_methods[exit_method].append({
            'coin': coin,
            'direction': direction,
            'entry': float(entry),
            'profit': profit,
            'tp_mult': float(tp_mult),
            'sl_mult': float(sl_mult)
        })
    
    return exit_methods

def analyze_exit_methods(exit_methods):
    """分析退出方式分布"""
    
    total_trades = sum(len(trades) for trades in exit_methods.values())
    
    print("=" * 80)
    print("📊 退出方式分布统计")
    print("=" * 80)
    print()
    
    # 按数量排序
    sorted_methods = sorted(exit_methods.items(), key=lambda x: len(x[1]), reverse=True)
    
    for exit_method, trades in sorted_methods:
        count = len(trades)
        percentage = count / total_trades * 100
        avg_profit = sum(t['profit'] for t in trades) / count
        
        # 统计正负利润
        positive = sum(1 for t in trades if t['profit'] > 0)
        negative = sum(1 for t in trades if t['profit'] < 0)
        zero = sum(1 for t in trades if t['profit'] == 0)
        
        print(f"【{exit_method}】")
        print(f"  数量: {count}笔 ({percentage:.1f}%)")
        print(f"  平均利润: {avg_profit:.2f}%")
        print(f"  正利润: {positive}笔 ({positive/count*100:.1f}%)")
        print(f"  负利润: {negative}笔 ({negative/count*100:.1f}%)")
        print(f"  零利润: {zero}笔 ({zero/count*100:.1f}%)")
        print()
    
    print("=" * 80)
    print("📈 关键发现")
    print("=" * 80)
    print()
    
    # 分析波动幅度判断的准确率
    amplitude_methods = ['take_profit_amplitude', 'stop_loss_amplitude']
    amplitude_trades = []
    for method in amplitude_methods:
        if method in exit_methods:
            amplitude_trades.extend(exit_methods[method])
    
    if amplitude_trades:
        tp_amplitude_trades = exit_methods.get('take_profit_amplitude', [])
        sl_amplitude_trades = exit_methods.get('stop_loss_amplitude', [])
        
        if tp_amplitude_trades:
            tp_avg = sum(t['profit'] for t in tp_amplitude_trades) / len(tp_amplitude_trades)
            tp_positive = sum(1 for t in tp_amplitude_trades if t['profit'] > 0)
            print(f"1️⃣ 波动幅度判断TP先触发（take_profit_amplitude）:")
            print(f"   - 数量: {len(tp_amplitude_trades)}笔")
            print(f"   - 平均利润: {tp_avg:.2f}%")
            print(f"   - 成功率: {tp_positive/len(tp_amplitude_trades)*100:.1f}%")
            print()
        
        if sl_amplitude_trades:
            sl_avg = sum(t['profit'] for t in sl_amplitude_trades) / len(sl_amplitude_trades)
            print(f"2️⃣ 波动幅度判断SL先触发（stop_loss_amplitude）:")
            print(f"   - 数量: {len(sl_amplitude_trades)}笔")
            print(f"   - 平均利润: {sl_avg:.2f}%")
            print()
    
    # 分析只触发一个的情况
    single_trigger = []
    for method in ['take_profit', 'stop_loss', 'timeout']:
        if method in exit_methods:
            single_trigger.extend(exit_methods[method])
    
    if single_trigger:
        print(f"3️⃣ 只触发一个目标（无需判断）:")
        print(f"   - 数量: {len(single_trigger)}笔")
        print(f"   - 占比: {len(single_trigger)/total_trades*100:.1f}%")
        print()
    
    # 估算判断准确率
    if tp_amplitude_trades:
        # 假设Phase 1平均利润15-16%
        phase1_profit = 16.0
        accuracy = (tp_avg / phase1_profit) * 100
        print(f"4️⃣ 波动幅度法判断准确率估算:")
        print(f"   - Phase 1客观利润: {phase1_profit:.2f}%")
        print(f"   - 波动幅度法TP利润: {tp_avg:.2f}%")
        print(f"   - 估算准确率: {accuracy:.1f}%")
        print()
    
    print("=" * 80)

def main():
    if len(sys.argv) < 2:
        print("用法: python analyze_exit_methods.py <backtest_log_file>")
        print("示例: python analyze_exit_methods.py backtest.log")
        sys.exit(1)
    
    log_file = sys.argv[1]
    
    try:
        exit_methods = parse_backtest_log(log_file)
        
        if not exit_methods:
            print("❌ 未找到调试记录，请确保日志文件包含V8.5.2.4.65的调试输出")
            sys.exit(1)
        
        analyze_exit_methods(exit_methods)
        
    except FileNotFoundError:
        print(f"❌ 文件不存在: {log_file}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ 分析失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()

