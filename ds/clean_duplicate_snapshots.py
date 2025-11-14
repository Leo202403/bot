#!/usr/bin/env python3
"""
清理现有重复数据的脚本

【功能】
- 清理market_snapshots中的重复数据
- 对于同一时间点的重复数据，保留volume最大的（更完整）
- 自动备份原文件
"""

import pandas as pd
from pathlib import Path
from datetime import datetime

def clean_duplicate_snapshots(model_name: str):
    """
    清理指定模型的重复快照数据
    
    规则：
    - 对于同一时间点的重复数据，保留volume最大的（更完整）
    - 按时间和币种排序
    """
    snapshot_dir = Path(f'/root/10-23-bot/ds/trading_data/{model_name}/market_snapshots')
    
    if not snapshot_dir.exists():
        print(f"❌ 目录不存在: {snapshot_dir}")
        return
    
    print(f"\n{'='*60}")
    print(f"清理 {model_name.upper()} 的重复数据")
    print(f"{'='*60}")
    
    csv_files = list(snapshot_dir.glob('*.csv'))
    print(f"找到 {len(csv_files)} 个CSV文件")
    
    total_removed = 0
    
    for csv_file in sorted(csv_files):
        try:
            # 读取文件
            df = pd.read_csv(csv_file, dtype={'time': str})
            original_count = len(df)
            
            # 检查是否有重复
            duplicates = df.duplicated(subset=['time', 'coin'], keep=False)
            duplicate_count = duplicates.sum()
            
            if duplicate_count == 0:
                print(f"  ✅ {csv_file.name}: 无重复数据 ({original_count}条)")
                continue
            
            print(f"  ⚠️  {csv_file.name}: 发现 {duplicate_count} 条重复数据")
            
            # 显示重复的时间点
            duplicate_times = df[duplicates]['time'].unique()
            print(f"     重复时间点: {', '.join(sorted(duplicate_times)[:5])}{'...' if len(duplicate_times) > 5 else ''}")
            
            # 备份原文件
            backup_file = csv_file.with_suffix('.csv.backup')
            df.to_csv(backup_file, index=False)
            print(f"     📦 已备份到: {backup_file.name}")
            
            # 去重：对于同一时间点和币种，保留volume最大的
            df_cleaned = df.sort_values('volume', ascending=False)
            df_cleaned = df_cleaned.drop_duplicates(subset=['time', 'coin'], keep='first')
            df_cleaned = df_cleaned.sort_values(['time', 'coin'])
            
            cleaned_count = len(df_cleaned)
            removed_count = original_count - cleaned_count
            total_removed += removed_count
            
            # 保存清理后的文件
            df_cleaned.to_csv(csv_file, index=False)
            
            print(f"     ✅ 清理完成: 移除 {removed_count} 条重复，保留 {cleaned_count} 条")
            
        except Exception as e:
            print(f"  ❌ {csv_file.name}: 清理失败 - {e}")
            import traceback
            traceback.print_exc()
    
    print(f"\n✅ {model_name.upper()} 清理完成！总共移除 {total_removed} 条重复数据")
    return total_removed

def main():
    """主函数"""
    print("============================================================")
    print("清理重复K线数据")
    print("============================================================")
    print(f"运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    qwen_removed = clean_duplicate_snapshots('qwen')
    deepseek_removed = clean_duplicate_snapshots('deepseek')
    
    print("\n============================================================")
    print("清理完成！")
    print("============================================================")
    print(f"\n📊 统计:")
    print(f"  Qwen: 移除 {qwen_removed} 条重复")
    print(f"  DeepSeek: 移除 {deepseek_removed} 条重复")
    print(f"  总计: 移除 {qwen_removed + deepseek_removed} 条重复")
    
    print("\n📝 下一步：")
    print("  1. 检查前端K线图是否正常显示")
    print("  2. 修改AI脚本，添加时机控制和去重逻辑")
    print("  3. 重启服务，让新逻辑生效")
    print("  4. 观察新数据是否还有重复")
    
    print("\n⚠️  注意：")
    print("  - 原文件已备份为 .csv.backup")
    print("  - 如需恢复，可以删除清理后的文件，重命名备份文件")

if __name__ == "__main__":
    main()

