#!/usr/bin/env python3
"""
K线数据保存修复脚本

【问题】
系统只保存了market_snapshots（市场快照），没有单独保存kline_data（K线数据）。
导致前端无法显示K线图。

【解决方案】
1. 临时方案：从现有market_snapshots中提取K线数据
2. 永久方案：修改get_ohlcv_data()函数，添加K线数据保存逻辑
"""

import json
import os
from pathlib import Path
from datetime import datetime, timedelta
import pandas as pd

def extract_klines_from_snapshots(model_name: str, days: int = 1):
    """
    从市场快照中提取K线数据用于前端显示
    
    Args:
        model_name: 模型名称（qwen或deepseek）
        days: 提取最近N天的数据
    """
    print(f"\n{'='*60}")
    print(f"提取 {model_name.upper()} 的K线数据")
    print(f"{'='*60}")
    
    snapshot_dir = Path(f'/root/10-23-bot/ds/trading_data/{model_name}/market_snapshots')
    kline_dir = Path(f'/root/10-23-bot/ds/trading_data/{model_name}/kline_data')
    kline_dir.mkdir(parents=True, exist_ok=True)
    
    if not snapshot_dir.exists():
        print(f"❌ 快照目录不存在: {snapshot_dir}")
        return
    
    # 获取最近N天的快照文件
    today = datetime.now()
    date_list = [(today - timedelta(days=i)).strftime('%Y%m%d') for i in range(days)]
    
    # 按币种分组存储K线数据
    klines_by_symbol = {}
    
    for date_str in date_list:
        snapshot_file = snapshot_dir / f"{date_str}.csv"
        
        if not snapshot_file.exists():
            print(f"⚠️ 快照文件不存在: {snapshot_file.name}")
            continue
        
        print(f"\n📄 读取: {snapshot_file.name}")
        
        try:
            # 读取CSV文件
            df = pd.read_csv(snapshot_file, on_bad_lines='skip', encoding='utf-8-sig')
            
            print(f"  ✓ 读取 {len(df)} 条记录")
            
            # 按币种分组
            for coin in df['coin'].unique():
                coin_data = df[df['coin'] == coin].copy()
                
                # 提取K线数据
                for _, row in coin_data.iterrows():
                    # 解析时间戳
                    time_str = str(row['time'])
                    if len(time_str) == 4:  # HHMM格式
                        hour = int(time_str[:2])
                        minute = int(time_str[2:])
                        dt = datetime.strptime(date_str, '%Y%m%d').replace(hour=hour, minute=minute)
                        timestamp = int(dt.timestamp() * 1000)
                    else:
                        continue
                    
                    kline = {
                        'timestamp': timestamp,
                        'open': float(row['open']),
                        'high': float(row['high']),
                        'low': float(row['low']),
                        'close': float(row['close']),
                        'volume': float(row['volume'])
                    }
                    
                    if coin not in klines_by_symbol:
                        klines_by_symbol[coin] = []
                    klines_by_symbol[coin].append(kline)
            
        except Exception as e:
            print(f"  ❌ 读取失败: {e}")
            continue
    
    # 保存每个币种的K线数据
    print(f"\n{'='*60}")
    print(f"保存K线数据文件")
    print(f"{'='*60}")
    
    for symbol, klines in klines_by_symbol.items():
        # 按时间戳排序
        klines.sort(key=lambda x: x['timestamp'])
        
        # 文件名：BTC_USDT_USDT_1m.json
        # 注意：这里假设symbol格式是 "BTC/USDT:USDT"
        file_name = f"{symbol}_USDT_USDT_15m.json"
        file_path = kline_dir / file_name
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(klines, f, ensure_ascii=False, indent=2)
        
        print(f"  ✓ {symbol}: {len(klines)} 条K线 → {file_name}")
    
    print(f"\n✅ {model_name.upper()} K线数据提取完成！")
    print(f"   保存位置: {kline_dir}")
    print(f"   币种数量: {len(klines_by_symbol)}")

def main():
    """主函数"""
    print("============================================================")
    print("K线数据提取工具")
    print("============================================================")
    print("从market_snapshots中提取K线数据用于前端显示")
    print("")
    
    # 提取最近1天的数据
    extract_klines_from_snapshots('qwen', days=1)
    extract_klines_from_snapshots('deepseek', days=1)
    
    print("\n============================================================")
    print("提取完成！")
    print("============================================================")
    print("\n下一步：")
    print("1. 检查前端是否能正常显示K线图")
    print("2. 如果能显示，说明临时方案有效")
    print("3. 然后需要修改AI脚本，添加永久保存逻辑")

if __name__ == "__main__":
    main()

