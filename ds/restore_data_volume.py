#!/usr/bin/env python3
"""
【V8.5.2.4.89.2】逐步恢复数据量
当前: 5天/300机会/4组合/400采样 → 内存峰值79MB
目标: 逐步恢复到14天/2000机会/8组合/800采样
"""

import re
import sys

# 定义3个恢复阶段
STAGES = {
    'stage1': {
        'name': '小幅增加（保守）',
        'lookback_days': 7,
        'max_opportunities': 500,
        'max_combinations': 6,
        'sample_size': 500,
        'expected_memory': '400-500MB'
    },
    'stage2': {
        'name': '中等增加',
        'lookback_days': 10,
        'max_opportunities': 1000,
        'max_combinations': 7,
        'sample_size': 600,
        'expected_memory': '500-700MB'
    },
    'stage3': {
        'name': '完全恢复',
        'lookback_days': 14,
        'max_opportunities': 2000,
        'max_combinations': 8,
        'sample_size': 800,
        'expected_memory': '700-900MB'
    }
}

def restore_stage(stage_name):
    """恢复到指定阶段"""
    if stage_name not in STAGES:
        print(f"❌ 无效阶段: {stage_name}")
        print(f"✓ 可用阶段: {', '.join(STAGES.keys())}")
        sys.exit(1)
    
    stage = STAGES[stage_name]
    files = ['deepseek_多币种智能版.py', 'qwen_多币种智能版.py']
    
    print(f"\n{'='*70}")
    print(f"🔄 恢复数据量到: {stage['name']}")
    print(f"{'='*70}")
    print(f"📊 目标参数:")
    print(f"   - 回测天数: {stage['lookback_days']}天")
    print(f"   - Phase 1机会数: {stage['max_opportunities']}个")
    print(f"   - Phase 2测试组合: {stage['max_combinations']}组")
    print(f"   - Phase 3采样: {stage['sample_size']}个")
    print(f"   - 预计内存: {stage['expected_memory']}")
    print(f"{'='*70}\n")
    
    for file in files:
        with open(file, 'r') as f:
            content = f.read()
        
        # 备份
        with open(f"{file}.before_restore_{stage_name}", 'w') as f:
            f.write(content)
        
        # 1. 恢复回测天数
        content = re.sub(
            r'lookback_days\s*=\s*\d+',
            f'lookback_days = {stage["lookback_days"]}',
            content
        )
        
        # 2. 恢复Phase 1机会数
        content = re.sub(
            r'max_opportunities\s*=\s*\d+',
            f'max_opportunities = {stage["max_opportunities"]}',
            content
        )
        
        # 3. 恢复Phase 2测试组合
        content = re.sub(
            r'max_combinations\s*=\s*\d+',
            f'max_combinations = {stage["max_combinations"]}',
            content
        )
        
        # 4. 恢复Phase 3采样
        content = re.sub(
            r'sample_size\s*=\s*\d+',
            f'sample_size = {stage["sample_size"]}',
            content
        )
        
        # 写回文件
        with open(file, 'w') as f:
            f.write(content)
        
        print(f"✓ 已恢复 {file}")
    
    print(f"\n{'='*70}")
    print(f"✅ 恢复完成！")
    print(f"{'='*70}")
    print(f"\n📝 下一步:")
    print(f"   1. 上传到服务器")
    print(f"   2. 运行回测并监控内存峰值")
    print(f"   3. 如果成功（内存<800MB），继续下一阶段")
    print(f"   4. 如果失败（OOM），回退到上一阶段\n")

if __name__ == '__main__':
    if len(sys.argv) != 2:
        print(f"用法: python3 restore_data_volume.py <stage>")
        print(f"\n可用阶段:")
        for stage_name, stage_info in STAGES.items():
            print(f"  {stage_name}: {stage_info['name']} (预计内存: {stage_info['expected_memory']})")
        sys.exit(1)
    
    restore_stage(sys.argv[1])

