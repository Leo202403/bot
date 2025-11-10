#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
V8.3.21 时区修复工具

问题：服务器之前使用北京时间（UTC+8），导致保存的时间戳比实际时间多了8小时
解决：将所有时间戳减去8小时，确保没有"未来"的记录

涉及的数据文件：
1. trades_history.csv - 交易历史
2. ai_decisions.json - AI决策历史
3. pnl_history.csv - 盈亏历史
4. market_snapshots/*.csv - 市场快照
"""

import pandas as pd
import json
from pathlib import Path
from datetime import datetime, timedelta
import shutil
from typing import List, Dict

# 配置
MODELS = ['qwen', 'deepseek']
BACKUP_SUFFIX = '.bak_before_timezone_fix'

def backup_file(file_path: Path):
    """
    备份文件
    """
    if file_path.exists():
        backup_path = file_path.parent / f"{file_path.name}{BACKUP_SUFFIX}"
        shutil.copy2(file_path, backup_path)
        print(f"  ✓ 已备份: {backup_path.name}")
        return True
    return False


def fix_csv_timestamps(file_path: Path, time_columns: List[str], dry_run: bool = False):
    """
    修复CSV文件中的时间戳（减去8小时）
    
    Args:
        file_path: CSV文件路径
        time_columns: 包含时间戳的列名列表
        dry_run: 是否只检查不修改
    """
    if not file_path.exists():
        print(f"  ⚠️  文件不存在: {file_path}")
        return
    
    print(f"\n{'[检查]' if dry_run else '[修复]'} {file_path.name}")
    
    try:
        # 读取CSV
        df = pd.read_csv(file_path)
        
        if df.empty:
            print(f"  ✓ 文件为空，跳过")
            return
        
        print(f"  📊 共{len(df)}条记录")
        
        # 检查时间列
        found_columns = [col for col in time_columns if col in df.columns]
        
        if not found_columns:
            print(f"  ⚠️  未找到时间列: {time_columns}")
            return
        
        # 修复每个时间列
        modified = False
        future_count = 0
        
        for col in found_columns:
            print(f"\n  处理列: {col}")
            
            # 检查是否有未来时间
            now = datetime.now()
            
            # 尝试解析时间
            for idx, value in df[col].items():
                if pd.isna(value):
                    continue
                
                try:
                    # 尝试多种时间格式
                    dt = None
                    for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M:%S.%f', '%Y-%m-%d']:
                        try:
                            dt = datetime.strptime(str(value), fmt)
                            break
                        except:
                            continue
                    
                    if dt and dt > now:
                        future_count += 1
                        if future_count <= 3:  # 只显示前3个示例
                            print(f"    ⚠️  发现未来时间: {dt} (当前: {now})")
                
                except Exception as e:
                    continue
            
            if future_count > 0:
                print(f"    🚨 发现{future_count}条未来记录！")
                
                if not dry_run:
                    # 修复：减去8小时
                    df[col] = pd.to_datetime(df[col], errors='coerce')
                    df[col] = df[col] - timedelta(hours=8)
                    modified = True
                    print(f"    ✓ 已修复：所有时间减去8小时")
            else:
                print(f"    ✓ 无未来时间，数据正常")
        
        # 保存修复后的文件
        if modified and not dry_run:
            # 备份原文件
            backup_file(file_path)
            
            # 保存修复后的文件
            df.to_csv(file_path, index=False, encoding='utf-8')
            print(f"\n  ✅ 文件已修复并保存")
        elif dry_run and future_count > 0:
            print(f"\n  💡 [干运行模式] 实际运行时将修复{future_count}条记录")
        else:
            print(f"\n  ✓ 无需修复")
    
    except Exception as e:
        print(f"  ❌ 处理失败: {e}")


def fix_json_timestamps(file_path: Path, dry_run: bool = False):
    """
    修复JSON文件中的时间戳（减去8小时）
    
    Args:
        file_path: JSON文件路径
        dry_run: 是否只检查不修改
    """
    if not file_path.exists():
        print(f"  ⚠️  文件不存在: {file_path}")
        return
    
    print(f"\n{'[检查]' if dry_run else '[修复]'} {file_path.name}")
    
    try:
        # 读取JSON
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        if not data:
            print(f"  ✓ 文件为空，跳过")
            return
        
        print(f"  📊 共{len(data)}条记录")
        
        # 检查时间字段
        modified = False
        future_count = 0
        now = datetime.now()
        
        for item in data:
            if 'timestamp' in item:
                try:
                    dt = datetime.fromisoformat(item['timestamp'])
                    
                    if dt > now:
                        future_count += 1
                        if future_count <= 3:
                            print(f"    ⚠️  发现未来时间: {dt} (当前: {now})")
                        
                        if not dry_run:
                            # 修复：减去8小时
                            fixed_dt = dt - timedelta(hours=8)
                            item['timestamp'] = fixed_dt.isoformat()
                            modified = True
                
                except Exception as e:
                    continue
        
        if future_count > 0:
            print(f"    🚨 发现{future_count}条未来记录！")
            
            if modified and not dry_run:
                # 备份原文件
                backup_file(file_path)
                
                # 保存修复后的文件
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                print(f"\n  ✅ 文件已修复并保存")
            elif dry_run:
                print(f"\n  💡 [干运行模式] 实际运行时将修复{future_count}条记录")
        else:
            print(f"    ✓ 无未来时间，数据正常")
            print(f"\n  ✓ 无需修复")
    
    except Exception as e:
        print(f"  ❌ 处理失败: {e}")


def fix_market_snapshots(snapshot_dir: Path, dry_run: bool = False):
    """
    修复market_snapshots目录下的所有CSV文件
    
    Args:
        snapshot_dir: market_snapshots目录路径
        dry_run: 是否只检查不修改
    """
    if not snapshot_dir.exists():
        print(f"  ⚠️  目录不存在: {snapshot_dir}")
        return
    
    print(f"\n{'='*60}")
    print(f"{'[检查]' if dry_run else '[修复]'} 市场快照目录: {snapshot_dir}")
    print(f"{'='*60}")
    
    # 获取所有CSV文件
    csv_files = list(snapshot_dir.glob("*.csv"))
    
    if not csv_files:
        print(f"  ⚠️  目录下没有CSV文件")
        return
    
    print(f"  📁 找到{len(csv_files)}个快照文件")
    
    # 只修复最近30天的数据（避免处理太多历史数据）
    recent_files = sorted(csv_files, reverse=True)[:30]
    
    for csv_file in recent_files:
        # market_snapshots中的time列通常是HH:MM格式，不是完整时间戳
        # 但文件名包含日期（YYYYMMDD.csv）
        # 主要检查文件修改时间是否在未来
        
        stat = csv_file.stat()
        file_mtime = datetime.fromtimestamp(stat.st_mtime)
        now = datetime.now()
        
        if file_mtime > now:
            print(f"\n  ⚠️  {csv_file.name}: 文件修改时间在未来 ({file_mtime})")
            
            if not dry_run:
                # 无法直接修改文件时间戳，但可以修正CSV内容
                # 市场快照的时间主要在文件名中，CSV内只有HH:MM
                print(f"    💡 市场快照文件的时间戳无需修复（时间在文件名中）")
        else:
            if csv_file == recent_files[0]:  # 只对第一个文件显示详情
                print(f"\n  ✓ {csv_file.name}: 时间正常 ({file_mtime})")


def main():
    """
    主函数
    """
    import argparse
    
    parser = argparse.ArgumentParser(description='V8.3.21 时区修复工具')
    parser.add_argument('--dry-run', action='store_true', help='只检查不修改（推荐先运行）')
    parser.add_argument('--model', choices=['qwen', 'deepseek', 'all'], default='all', help='指定修复哪个模型的数据')
    args = parser.parse_args()
    
    print("=" * 80)
    print("V8.3.21 时区修复工具")
    print("=" * 80)
    print(f"模式: {'检查模式（不会修改文件）' if args.dry_run else '修复模式（会修改文件）'}")
    print(f"范围: {args.model}")
    print()
    
    if not args.dry_run:
        confirm = input("⚠️  确认要修复数据吗？将会备份原文件。(yes/no): ")
        if confirm.lower() != 'yes':
            print("❌ 已取消")
            return
    
    # 确定要处理的模型
    models_to_fix = MODELS if args.model == 'all' else [args.model]
    
    for model in models_to_fix:
        print(f"\n{'='*80}")
        print(f"处理模型: {model.upper()}")
        print(f"{'='*80}")
        
        data_dir = Path("trading_data") / model
        
        if not data_dir.exists():
            print(f"  ⚠️  数据目录不存在: {data_dir}")
            continue
        
        # 1. 修复交易历史
        print(f"\n{'─'*60}")
        print("1. 交易历史 (trades_history.csv)")
        print(f"{'─'*60}")
        fix_csv_timestamps(
            data_dir / "trades_history.csv",
            time_columns=['开仓时间', '平仓时间', '创建时间', 'create_time'],
            dry_run=args.dry_run
        )
        
        # 2. 修复盈亏历史
        print(f"\n{'─'*60}")
        print("2. 盈亏历史 (pnl_history.csv)")
        print(f"{'─'*60}")
        fix_csv_timestamps(
            data_dir / "pnl_history.csv",
            time_columns=['time', 'timestamp', '时间'],
            dry_run=args.dry_run
        )
        
        # 3. 修复AI决策历史
        print(f"\n{'─'*60}")
        print("3. AI决策历史 (ai_decisions.json)")
        print(f"{'─'*60}")
        fix_json_timestamps(
            data_dir / "ai_decisions.json",
            dry_run=args.dry_run
        )
        
        # 4. 修复市场快照
        print(f"\n{'─'*60}")
        print("4. 市场快照 (market_snapshots/*.csv)")
        print(f"{'─'*60}")
        fix_market_snapshots(
            data_dir / "market_snapshots",
            dry_run=args.dry_run
        )
    
    print(f"\n{'='*80}")
    if args.dry_run:
        print("✅ 检查完成！")
        print("💡 如确认需要修复，请运行: python3 fix_timezone_data.py")
    else:
        print("✅ 修复完成！")
        print("💡 备份文件已保存（后缀.bak_before_timezone_fix）")
        print("💡 如有问题，可从备份恢复")
    print(f"{'='*80}")


if __name__ == '__main__':
    main()

