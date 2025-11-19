#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简化版退出方式分析（从stdin或grep输出）
用法：
  cat backtest.log | grep "退出方式" | python analyze_exit_simple.py
  或
  python analyze_exit_simple.py < backtest.log
"""

import sys
import re
from collections import defaultdict

def main():
    exit_methods = defaultdict(list)
    
    print("📖 读取调试日志...", file=sys.stderr)
    
    for line in sys.stdin:
        # 匹配退出方式和利润
        match = re.search(r'退出方式:\s*([^,]+),.*?利润:\s*([-\d.]+)%', line)
        if match:
            exit_method = match.group(1).strip()
            profit = float(match.group(2))
            exit_methods[exit_method].append(profit)
    
    if not exit_methods:
        print("\n❌ 未找到退出方式数据", file=sys.stderr)
        print("💡 请确保输入包含 '退出方式: xxx, 利润: xx%' 格式", file=sys.stderr)
        sys.exit(1)
    
    # 统计
    total = sum(len(profits) for profits in exit_methods.values())
    
    print("\n" + "=" * 80)
    print("📊 退出方式分布统计")
    print("=" * 80)
    print()
    
    # 按数量排序
    sorted_methods = sorted(exit_methods.items(), key=lambda x: len(x[1]), reverse=True)
    
    for exit_method, profits in sorted_methods:
        count = len(profits)
        percentage = count / total * 100
        avg_profit = sum(profits) / count
        positive = sum(1 for p in profits if p > 0)
        negative = sum(1 for p in profits if p < 0)
        zero = sum(1 for p in profits if p == 0)
        
        print(f"【{exit_method}】")
        print(f"  📊 数量: {count}笔 ({percentage:.1f}%)")
        print(f"  💰 平均利润: {avg_profit:.2f}%")
        print(f"  ✅ 正利润: {positive}笔 ({positive/count*100:.1f}%)")
        print(f"  ❌ 负利润: {negative}笔 ({negative/count*100:.1f}%)")
        if zero > 0:
            print(f"  ⚠️  零利润: {zero}笔 ({zero/count*100:.1f}%)")
        print()
    
    print("=" * 80)
    print("🔍 关键分析")
    print("=" * 80)
    print()
    
    # 分析波动幅度判断
    tp_amp = exit_methods.get('take_profit_amplitude', [])
    sl_amp = exit_methods.get('stop_loss_amplitude', [])
    
    if tp_amp or sl_amp:
        print("【波动幅度判断（需要推测TP/SL触发顺序）】")
        if tp_amp:
            tp_avg = sum(tp_amp) / len(tp_amp)
            tp_pos = sum(1 for p in tp_amp if p > 0)
            print(f"  ✅ 判断TP先触发: {len(tp_amp)}笔, 平均{tp_avg:.2f}%, 成功率{tp_pos/len(tp_amp)*100:.1f}%")
        if sl_amp:
            sl_avg = sum(sl_amp) / len(sl_amp)
            print(f"  ❌ 判断SL先触发: {len(sl_amp)}笔, 平均{sl_avg:.2f}%")
        print()
    
    # 分析只触发一个的情况
    single_tp = exit_methods.get('take_profit', [])
    single_sl = exit_methods.get('stop_loss', [])
    timeout = exit_methods.get('timeout', [])
    
    single_total = len(single_tp) + len(single_sl) + len(timeout)
    if single_total > 0:
        print("【只触发一个目标（无需判断）】")
        if single_tp:
            print(f"  ✅ 只触发TP: {len(single_tp)}笔, 平均{sum(single_tp)/len(single_tp):.2f}%")
        if single_sl:
            print(f"  ❌ 只触发SL: {len(single_sl)}笔, 平均{sum(single_sl)/len(single_sl):.2f}%")
        if timeout:
            print(f"  ⏰ 超时退出: {len(timeout)}笔, 平均{sum(timeout)/len(timeout):.2f}%")
        print(f"  📊 小计: {single_total}笔 ({single_total/total*100:.1f}%)")
        print()
    
    # 估算准确率
    if tp_amp:
        phase1_profit = 16.0  # Phase 1客观利润
        tp_avg = sum(tp_amp) / len(tp_amp)
        print("【准确率估算】")
        print(f"  📊 Phase 1客观利润: ~{phase1_profit:.0f}%")
        print(f"  📊 波动幅度判断TP平均利润: {tp_avg:.2f}%")
        print(f"  📊 捕获率: {tp_avg/phase1_profit*100:.1f}%")
        print()
        
        # 估算判断错误率
        if len(tp_amp) + len(sl_amp) > 0:
            need_judge = len(tp_amp) + len(sl_amp)
            print(f"  💡 需要判断的机会: {need_judge}笔 ({need_judge/total*100:.1f}%)")
            print(f"  💡 判断为TP先触发: {len(tp_amp)}笔 ({len(tp_amp)/need_judge*100:.1f}%)")
            print(f"  💡 判断为SL先触发: {len(sl_amp)}笔 ({len(sl_amp)/need_judge*100:.1f}%)")
    
    print("=" * 80)
    print(f"✅ 总计分析: {total}笔交易")
    print("=" * 80)

if __name__ == "__main__":
    main()

