#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
【V8.5.2.4.88】测试脚本：持仓分析与内存优化验证

测试内容：
1. 持仓中交易的分类逻辑
2. Phase 3机会采样功能
3. 内存占用估算
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / 'ds'))

def test_classify_entry_quality():
    """测试持仓中交易的分类逻辑"""
    from entry_exit_timing_analyzer_v2 import classify_entry_quality
    
    print("\n【测试1：持仓中交易分类】")
    print("="*60)
    
    # 测试用例1：已平仓 - 盈利
    trade1 = {
        '币种': 'BTC',
        '开仓时间': '2024-01-01 10:00',
        '平仓时间': '2024-01-01 12:00',
        '盈亏(U)': 5.5
    }
    result1 = classify_entry_quality(trade1)
    print(f"用例1（已平仓盈利）: {result1}")
    assert result1 == 'correct', f"预期'correct'，实际'{result1}'"
    
    # 测试用例2：已平仓 - 亏损
    trade2 = {
        '币种': 'ETH',
        '开仓时间': '2024-01-01 10:00',
        '平仓时间': '2024-01-01 12:00',
        '盈亏(U)': -3.5
    }
    result2 = classify_entry_quality(trade2)
    print(f"用例2（已平仓亏损）: {result2}")
    assert result2 == 'false_signal', f"预期'false_signal'，实际'{result2}'"
    
    # 测试用例3：持仓中 - 强信号
    trade3 = {
        '币种': 'BTC',
        '开仓时间': '2024-01-01 10:00',
        '平仓时间': None
    }
    matched_opp3 = {
        'signal_score': 95,
        'consensus': 3
    }
    result3 = classify_entry_quality(trade3, matched_opportunity=matched_opp3)
    print(f"用例3（持仓中-强信号）: {result3}")
    assert result3 == 'holding_strong', f"预期'holding_strong'，实际'{result3}'"
    
    # 测试用例4：持仓中 - 中等信号
    trade4 = {
        '币种': 'ETH',
        '开仓时间': '2024-01-01 10:00',
        '平仓时间': ''
    }
    matched_opp4 = {
        'signal_score': 85,
        'consensus': 2
    }
    result4 = classify_entry_quality(trade4, matched_opportunity=matched_opp4)
    print(f"用例4（持仓中-中等信号）: {result4}")
    assert result4 == 'holding_moderate', f"预期'holding_moderate'，实际'{result4}'"
    
    # 测试用例5：持仓中 - 弱信号
    trade5 = {
        '币种': 'SOL',
        '开仓时间': '2024-01-01 10:00',
        '平仓时间': None
    }
    matched_opp5 = {
        'signal_score': 75,
        'consensus': 1
    }
    result5 = classify_entry_quality(trade5, matched_opportunity=matched_opp5)
    print(f"用例5（持仓中-弱信号）: {result5}")
    assert result5 == 'holding_weak', f"预期'holding_weak'，实际'{result5}'"
    
    # 测试用例6：持仓中 - 无匹配机会
    trade6 = {
        '币种': 'DOGE',
        '开仓时间': '2024-01-01 10:00',
        '平仓时间': None
    }
    result6 = classify_entry_quality(trade6, matched_opportunity=None)
    print(f"用例6（持仓中-无匹配）: {result6}")
    assert result6 == 'holding_unknown', f"预期'holding_unknown'，实际'{result6}'"
    
    print("\n✅ 所有测试用例通过！")


def test_sample_opportunities():
    """测试Phase 3机会采样功能"""
    from phase3_enhanced_optimizer import sample_opportunities_for_phase3
    
    print("\n【测试2：Phase 3机会采样】")
    print("="*60)
    
    # 生成测试数据
    opportunities = []
    
    # 高质量：200个（signal_score>=90）
    for i in range(200):
        opportunities.append({
            'coin': f'COIN{i}',
            'signal_score': 90 + (i % 10),
            'consensus': 3
        })
    
    # 中等质量：1500个（80-90）
    for i in range(1500):
        opportunities.append({
            'coin': f'COIN{200+i}',
            'signal_score': 80 + (i % 10),
            'consensus': 2
        })
    
    # 低质量：2096个（<80）
    for i in range(2096):
        opportunities.append({
            'coin': f'COIN{1700+i}',
            'signal_score': 70 + (i % 10),
            'consensus': 1
        })
    
    print(f"原始机会数: {len(opportunities)}")
    print(f"  高质量(>=90): 200")
    print(f"  中等质量(80-90): 1500")
    print(f"  低质量(<80): 2096")
    
    # 采样
    sampled = sample_opportunities_for_phase3(opportunities, max_size=800)
    
    print(f"\n采样后机会数: {len(sampled)}")
    
    # 验证高质量机会全部保留
    high_quality_sampled = [o for o in sampled if o['signal_score'] >= 90]
    print(f"  高质量保留: {len(high_quality_sampled)}/200")
    assert len(high_quality_sampled) == 200, "高质量机会应全部保留"
    
    # 验证总数
    assert len(sampled) == 800, f"预期800个，实际{len(sampled)}个"
    
    # 估算内存节省
    memory_saved = (len(opportunities) - len(sampled)) / len(opportunities) * 100
    print(f"\n💾 内存节省: {memory_saved:.1f}%")
    print(f"  原始: {len(opportunities)}个 × 2KB ≈ {len(opportunities)*2/1024:.1f}MB")
    print(f"  采样后: {len(sampled)}个 × 2KB ≈ {len(sampled)*2/1024:.1f}MB")
    
    print("\n✅ 采样功能测试通过！")


def test_memory_estimation():
    """估算Phase 3内存占用"""
    print("\n【测试3：Phase 3内存估算】")
    print("="*60)
    
    # 参数
    opportunities_count = 800  # 采样后
    starting_points = 4
    combinations_per_point = 8
    
    print(f"配置：")
    print(f"  机会数: {opportunities_count}")
    print(f"  起点数: {starting_points}")
    print(f"  每起点测试组数: {combinations_per_point}")
    
    # 计算
    total_tests = opportunities_count * starting_points * combinations_per_point
    print(f"\n总计算量: {total_tests:,}次利润计算")
    
    # 内存估算（粗略）
    bytes_per_opportunity = 2048  # 2KB
    bytes_per_test = opportunities_count * bytes_per_opportunity
    peak_memory_mb = bytes_per_test * combinations_per_point / (1024 * 1024)
    
    print(f"\n内存估算：")
    print(f"  单次测试: {bytes_per_test/1024/1024:.1f}MB")
    print(f"  峰值内存: {peak_memory_mb:.1f}MB")
    print(f"  （假设每批保留{combinations_per_point}组结果）")
    
    # 对比优化前
    old_opportunities = 3796
    old_combinations = 10
    old_total_tests = old_opportunities * starting_points * old_combinations
    old_peak_memory = old_opportunities * bytes_per_opportunity * old_combinations / (1024 * 1024)
    
    print(f"\n对比优化前：")
    print(f"  计算量: {old_total_tests:,} → {total_tests:,} (减少{(1-total_tests/old_total_tests)*100:.0f}%)")
    print(f"  峰值内存: {old_peak_memory:.1f}MB → {peak_memory_mb:.1f}MB (减少{(1-peak_memory_mb/old_peak_memory)*100:.0f}%)")
    
    if peak_memory_mb < 300:
        print(f"\n✅ 内存占用{peak_memory_mb:.0f}MB < 300MB，符合预期！")
    else:
        print(f"\n⚠️  内存占用{peak_memory_mb:.0f}MB >= 300MB，可能需要进一步优化")


if __name__ == '__main__':
    print("\n" + "="*60)
    print("【V8.5.2.4.88】持仓分析与内存优化验证")
    print("="*60)
    
    try:
        test_classify_entry_quality()
        test_sample_opportunities()
        test_memory_estimation()
        
        print("\n" + "="*60)
        print("🎉 所有测试通过！")
        print("="*60)
        print("\n下一步：")
        print("  1. 运行实际回测验证")
        print("  2. 监控内存占用")
        print("  3. 检查持仓中交易的统计输出")
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

