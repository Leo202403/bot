#!/usr/bin/env python3
"""
K线数据时机和去重修复脚本

【修复目标】
1. 延后获取：等K线完成后再获取（如9:00的K线在9:01获取）
2. 保存去重：检查当前时间点是否已有数据，有则跳过

【修复位置】
1. save_market_snapshot_v7() - 添加去重逻辑
2. 主循环 - 添加时机控制逻辑
"""

# 这是修复代码的模板，需要手动应用到实际文件中

FIX_1_TIMING_CHECK = '''
# 【V8.5.2新增】在主循环开始前，检查是否应该获取数据
def should_fetch_kline_data():
    """
    检查当前时间是否适合获取K线数据
    
    规则：
    - 15分钟K线在每个15分钟周期的第1分钟获取
    - 例如：9:00的K线在9:01获取，确保K线已完全形成
    
    Returns:
        bool: True表示应该获取，False表示跳过
    """
    from datetime import datetime
    
    current_time = datetime.now()
    current_minute = current_time.minute
    
    # 检查是否在15分钟周期的第1分钟
    # 0:01, 0:16, 0:31, 0:46, 1:01, 1:16...
    if current_minute % 15 == 1:
        print(f"✅ 时机正确：{current_time.strftime('%H:%M')} - 可以获取上一个15分钟K线")
        return True
    else:
        print(f"⏰ 时机不对：{current_time.strftime('%H:%M')} - 跳过本次获取（等待K线完成）")
        return False

# 在主循环中使用
if __name__ == "__main__":
    # ... 现有代码 ...
    
    while True:
        try:
            # 【V8.5.2新增】检查时机
            if not should_fetch_kline_data():
                time.sleep(30)  # 等待30秒后再检查
                continue
            
            # 获取市场数据
            market_data_list = []
            for symbol in SYMBOLS:
                data = get_ohlcv_data(symbol)
                market_data_list.append(data)
            
            # 保存市场快照
            save_market_snapshot_v7(market_data_list)
            
            # ... 现有代码继续 ...
            
        except Exception as e:
            print(f"❌ 主循环错误: {e}")
            time.sleep(60)
'''

FIX_2_DEDUP_LOGIC = '''
def save_market_snapshot_v7(market_data_list):
    """保存市场快照（每15分钟）供复盘分析"""
    try:
        from pathlib import Path
        from datetime import datetime
        import pandas as pd
        
        model_name = os.getenv("MODEL_NAME", "deepseek")
        snapshot_dir = Path("trading_data") / model_name / "market_snapshots"
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        
        today = datetime.now().strftime("%Y%m%d")
        snapshot_file = snapshot_dir / f"{today}.csv"
        
        # ... 现有代码：准备快照数据 ...
        
        # 【V8.5.2新增】去重逻辑：检查当前时间点是否已有数据
        if snapshot_file.exists():
            try:
                existing_df = pd.read_csv(snapshot_file, dtype={'time': str})
                
                # 获取当前要保存的时间点
                current_time_str = None
                if snapshot_data:
                    current_time_str = snapshot_data[0].get('time')
                
                if current_time_str:
                    # 检查这个时间点是否已存在
                    existing_times = existing_df['time'].unique()
                    
                    if current_time_str in existing_times:
                        print(f"⏭️  跳过保存：时间点 {current_time_str} 的数据已存在")
                        
                        # 【可选】检查是否需要更新（如果新数据更完整）
                        existing_coins = set(existing_df[existing_df['time'] == current_time_str]['coin'].values)
                        new_coins = set([row['coin'] for row in snapshot_data])
                        
                        if new_coins - existing_coins:
                            print(f"  ℹ️  新数据包含额外币种: {new_coins - existing_coins}")
                            # 可以选择合并，但这里我们选择跳过
                        
                        return  # 跳过保存
                    else:
                        print(f"✅ 时间点 {current_time_str} 尚未保存，继续保存")
                
            except Exception as e:
                print(f"⚠️ 读取现有文件失败: {e}，将直接追加")
        
        # 保存数据（追加模式）
        df_new = pd.DataFrame(snapshot_data)
        
        if snapshot_file.exists():
            # 追加到现有文件
            df_new.to_csv(snapshot_file, mode='a', header=False, index=False)
            print(f"✓ 已追加市场快照: {len(snapshot_data)}条记录")
        else:
            # 创建新文件
            df_new.to_csv(snapshot_file, index=False)
            print(f"✓ 已创建市场快照: {len(snapshot_data)}条记录")
        
    except Exception as e:
        print(f"❌ 保存市场快照失败: {e}")
        import traceback
        traceback.print_exc()
'''

FIX_3_CLEAN_EXISTING_DATA = '''
#!/usr/bin/env python3
"""
清理现有重复数据的脚本
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
    
    print(f"\\n{'='*60}")
    print(f"清理 {model_name.upper()} 的重复数据")
    print(f"{'='*60}")
    
    csv_files = list(snapshot_dir.glob('*.csv'))
    print(f"找到 {len(csv_files)} 个CSV文件")
    
    for csv_file in csv_files:
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
            
            # 备份原文件
            backup_file = csv_file.with_suffix('.csv.backup')
            df.to_csv(backup_file, index=False)
            print(f"     已备份到: {backup_file.name}")
            
            # 去重：对于同一时间点和币种，保留volume最大的
            df_cleaned = df.sort_values('volume', ascending=False)
            df_cleaned = df_cleaned.drop_duplicates(subset=['time', 'coin'], keep='first')
            df_cleaned = df_cleaned.sort_values(['time', 'coin'])
            
            cleaned_count = len(df_cleaned)
            removed_count = original_count - cleaned_count
            
            # 保存清理后的文件
            df_cleaned.to_csv(csv_file, index=False)
            
            print(f"     ✅ 清理完成: 移除 {removed_count} 条重复，保留 {cleaned_count} 条")
            
        except Exception as e:
            print(f"  ❌ {csv_file.name}: 清理失败 - {e}")
    
    print(f"\\n✅ {model_name.upper()} 清理完成！")

def main():
    """主函数"""
    print("============================================================")
    print("清理重复K线数据")
    print("============================================================")
    print(f"运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    clean_duplicate_snapshots('qwen')
    clean_duplicate_snapshots('deepseek')
    
    print("\\n============================================================")
    print("清理完成！")
    print("============================================================")
    print("\\n下一步：")
    print("1. 检查前端K线图是否正常显示")
    print("2. 重启服务，让新的时机控制和去重逻辑生效")
    print("3. 观察新数据是否还有重复")

if __name__ == "__main__":
    main()
'''

def main():
    """显示修复说明"""
    print("=" * 70)
    print("K线数据时机和去重修复方案")
    print("=" * 70)
    
    print("\\n【修复1：时机控制】")
    print("-" * 70)
    print("在主循环中添加时机检查，确保在K线完成后再获取")
    print("\\n代码位置：deepseek_多币种智能版.py 和 qwen_多币种智能版.py 的主循环")
    print("\\n" + FIX_1_TIMING_CHECK)
    
    print("\\n" + "=" * 70)
    print("【修复2：保存去重】")
    print("-" * 70)
    print("在save_market_snapshot_v7()中添加去重逻辑")
    print("\\n代码位置：deepseek_多币种智能版.py 和 qwen_多币种智能版.py")
    print("\\n" + FIX_2_DEDUP_LOGIC)
    
    print("\\n" + "=" * 70)
    print("【修复3：清理现有数据】")
    print("-" * 70)
    print("运行脚本清理已有的重复数据")
    print("\\n保存为：clean_duplicate_snapshots.py")
    print("\\n" + FIX_3_CLEAN_EXISTING_DATA)
    
    print("\\n" + "=" * 70)
    print("实施步骤")
    print("=" * 70)
    print("""
1. 创建清理脚本
   cd /root/10-23-bot/ds
   cat > clean_duplicate_snapshots.py << 'EOF'
   [粘贴 FIX_3_CLEAN_EXISTING_DATA 的内容]
   EOF

2. 运行清理脚本
   python3 clean_duplicate_snapshots.py

3. 修改AI脚本（两个文件都要改）
   - deepseek_多币种智能版.py
   - qwen_多币种智能版.py
   
   修改内容：
   a) 添加 should_fetch_kline_data() 函数
   b) 在主循环中调用时机检查
   c) 修改 save_market_snapshot_v7() 添加去重逻辑

4. 重启服务
   bash ~/快速重启_修复版.sh

5. 验证
   - 观察日志，确认时机控制生效
   - 检查新数据是否还有重复
   - 确认前端K线图正常显示
    """)

if __name__ == "__main__":
    main()

