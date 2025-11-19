#!/usr/bin/env python3
"""
【V8.5.2.4.47】检查共振数据诊断工具

用途：
1. 检查市场快照CSV中是否包含indicator_consensus字段
2. 检查昨日订单CSV中是否包含共振指标数/indicator_consensus字段
3. 显示实际数据样本

使用方法：
python3 check_consensus_data.py
"""

import os
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta

def check_consensus_data():
    """检查共振数据"""
    print("=" * 70)
    print("🔍 共振数据诊断工具")
    print("=" * 70)
    
    # 获取model_name
    model_name = os.getenv("MODEL_NAME", "deepseek")
    data_dir = Path("trading_data") / model_name
    
    # 检查1：市场快照CSV
    print("\n📊 检查1：市场快照CSV文件")
    print("-" * 70)
    
    snapshot_dir = data_dir / "market_snapshots"
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
    
    # 【修复】实际文件名是 {date}.csv，而不是 kline_snapshots_{date}.csv
    snapshot_file = snapshot_dir / f"{yesterday}.csv"
    if snapshot_file.exists():
        print(f"✓ 找到文件: {snapshot_file}")
        df = pd.read_csv(snapshot_file)
        print(f"  总行数: {len(df)}")
        print(f"  总列数: {len(df.columns)}")
        
        # 检查关键字段
        print(f"\n  关键字段检查:")
        fields_to_check = [
            'indicator_consensus', 
            'trend_15m', 
            'trend_1h', 
            'trend_4h',
            'ema20_1h',
            'ema50_1h',
            'signal_score'
        ]
        
        for field in fields_to_check:
            if field in df.columns:
                # 统计非零值
                non_zero = (df[field] != 0).sum() if field in ['indicator_consensus', 'signal_score'] else len(df)
                print(f"    ✓ {field:25s}: 存在 (非零: {non_zero}/{len(df)})")
            else:
                print(f"    ✗ {field:25s}: 缺失 ⚠️")
        
        # 显示前3行数据
        if 'indicator_consensus' in df.columns:
            print(f"\n  前3行indicator_consensus值:")
            for i in range(min(3, len(df))):
                row = df.iloc[i]
                coin = row.get('coin', 'N/A')
                time = row.get('time', 'N/A')
                consensus = row.get('indicator_consensus', 0)
                print(f"    [{i+1}] {coin:8s} {time:10s} consensus={consensus}")
            
            # 统计共振值分布
            print(f"\n  共振值分布:")
            consensus_counts = df['indicator_consensus'].value_counts().sort_index()
            for value, count in consensus_counts.items():
                percentage = count / len(df) * 100
                print(f"    {int(value)}: {count:4d}笔 ({percentage:5.1f}%)")
        else:
            print(f"\n  ⚠️ indicator_consensus字段不存在！")
    else:
        print(f"✗ 文件不存在: {snapshot_file}")
    
    # 检查2：交易历史CSV
    print(f"\n📊 检查2：交易历史CSV文件")
    print("-" * 70)
    
    # 【修复】实际文件是 trades_history.csv，不是按日期分开的
    orders_file = data_dir / "trades_history.csv"
    if orders_file.exists():
        print(f"✓ 找到文件: {orders_file}")
        df = pd.read_csv(orders_file, encoding='utf-8-sig')
        print(f"  总行数: {len(df)}")
        print(f"  总列数: {len(df.columns)}")
        
        # 筛选昨日交易（开仓时间或平仓时间在昨日）
        yesterday_formatted = f"{yesterday[:4]}-{yesterday[4:6]}-{yesterday[6:]}"
        if '开仓时间' in df.columns:
            yesterday_trades = df[
                (df['开仓时间'].astype(str).str.contains(yesterday_formatted, na=False)) |
                (df['平仓时间'].astype(str).str.contains(yesterday_formatted, na=False))
            ]
            print(f"  昨日交易: {len(yesterday_trades)}笔")
        
        # 检查关键字段
        print(f"\n  关键字段检查:")
        fields_to_check = [
            '共振指标数',
            'indicator_consensus',
            '信号分数',
            'signal_score',
            '币种',
            '方向',
            '开仓价格',
            '盈亏(U)'
        ]
        
        for field in fields_to_check:
            if field in df.columns:
                print(f"    ✓ {field:25s}: 存在")
            else:
                print(f"    ✗ {field:25s}: 缺失 ⚠️")
        
        # 显示昨日前3笔交易数据
        print(f"\n  昨日前3笔交易数据:")
        display_df = yesterday_trades if 'yesterday_trades' in locals() and len(yesterday_trades) > 0 else df
        for i in range(min(3, len(display_df))):
            row = display_df.iloc[i]
            coin = row.get('币种', 'N/A')
            
            # 尝试读取共振值（中文和英文）
            consensus_cn = row.get('共振指标数', 'N/A')
            consensus_en = row.get('indicator_consensus', 'N/A')
            
            # 尝试读取信号分（中文和英文）
            score_cn = row.get('信号分数', 'N/A')
            score_en = row.get('signal_score', 'N/A')
            
            print(f"    [{i+1}] 币种: {coin}")
            print(f"        共振指标数: {consensus_cn}")
            print(f"        indicator_consensus: {consensus_en}")
            print(f"        信号分数: {score_cn}")
            print(f"        signal_score: {score_en}")
        
        # 统计共振值分布（如果字段存在）
        if 'yesterday_trades' in locals() and len(yesterday_trades) > 0:
            stat_df = yesterday_trades
            stat_label = "昨日交易"
        else:
            stat_df = df
            stat_label = "全部交易"
            
        if '共振指标数' in stat_df.columns:
            print(f"\n  共振值分布（'共振指标数' - {stat_label}）:")
            consensus_counts = stat_df['共振指标数'].value_counts().sort_index()
            for value, count in consensus_counts.items():
                percentage = count / len(stat_df) * 100
                print(f"    {value}: {count:4d}笔 ({percentage:5.1f}%)")
        elif 'indicator_consensus' in stat_df.columns:
            print(f"\n  共振值分布（'indicator_consensus' - {stat_label}）:")
            consensus_counts = stat_df['indicator_consensus'].value_counts().sort_index()
            for value, count in consensus_counts.items():
                percentage = count / len(stat_df) * 100
                print(f"    {value}: {count:4d}笔 ({percentage:5.1f}%)")
        else:
            print(f"\n  ⚠️ 两个共振字段都不存在！")
    else:
        print(f"✗ 文件不存在: {orders_file}")
    
    # 检查3：最新的market snapshot文件
    print(f"\n📊 检查3：最新市场快照文件")
    print("-" * 70)
    
    if snapshot_dir.exists():
        # 找到最新的CSV文件（文件名格式：YYYYMMDD.csv）
        csv_files = sorted(snapshot_dir.glob("*.csv"), reverse=True)
        if csv_files:
            latest_file = csv_files[0]
            print(f"✓ 最新文件: {latest_file.name}")
            
            df = pd.read_csv(latest_file)
            print(f"  总行数: {len(df)}")
            
            if 'indicator_consensus' in df.columns:
                non_zero = (df['indicator_consensus'] != 0).sum()
                print(f"  indicator_consensus字段: 存在")
                print(f"  非零值数量: {non_zero}/{len(df)} ({non_zero/len(df)*100:.1f}%)")
                
                # 显示最后3行
                print(f"\n  最后3行数据:")
                for i in range(max(0, len(df)-3), len(df)):
                    row = df.iloc[i]
                    coin = row.get('coin', 'N/A')
                    time = row.get('time', 'N/A')
                    consensus = row.get('indicator_consensus', 0)
                    print(f"    {coin:8s} {time:10s} consensus={consensus}")
            else:
                print(f"  ⚠️ indicator_consensus字段不存在！")
        else:
            print(f"  ⚠️ 没有找到任何快照文件")
    else:
        print(f"✗ 快照目录不存在: {snapshot_dir}")
    
    print("\n" + "=" * 70)
    print("🎯 诊断完成！")
    print("=" * 70)

if __name__ == "__main__":
    try:
        check_consensus_data()
    except Exception as e:
        print(f"\n❌ 发生错误: {e}")
        import traceback
        traceback.print_exc()

