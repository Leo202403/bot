#!/usr/bin/env python3
"""
检查K线数据完整性
"""

import json
import os
from datetime import datetime
from pathlib import Path

def check_kline_file(model_name: str, symbol: str):
    """检查单个币种的K线数据"""
    kline_dir = f'/root/10-23-bot/ds/trading_data/{model_name}/kline_data'
    file_path = f'{kline_dir}/{symbol.replace("/", "_")}_1m.json'
    
    print(f"\n{'='*60}")
    print(f"检查 {model_name.upper()} - {symbol}")
    print(f"{'='*60}")
    
    if not os.path.exists(file_path):
        print(f"❌ 文件不存在: {file_path}")
        return False
    
    try:
        # 获取文件大小
        file_size = os.path.getsize(file_path)
        print(f"📁 文件大小: {file_size:,} bytes ({file_size/1024:.2f} KB)")
        
        # 获取文件修改时间
        mtime = os.path.getmtime(file_path)
        mtime_str = datetime.fromtimestamp(mtime).strftime('%Y-%m-%d %H:%M:%S')
        print(f"🕐 最后修改: {mtime_str}")
        
        # 读取文件内容
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        if not data:
            print(f"❌ 文件为空")
            return False
        
        # 检查数据结构
        if not isinstance(data, list):
            print(f"❌ 数据格式错误（应该是列表）: {type(data)}")
            return False
        
        print(f"✅ 数据条数: {len(data)}")
        
        if len(data) == 0:
            print(f"❌ 数据为空列表")
            return False
        
        # 检查第一条和最后一条数据
        first_item = data[0]
        last_item = data[-1]
        
        print(f"\n📊 数据范围:")
        print(f"  第一条: {first_item}")
        print(f"  最后条: {last_item}")
        
        # 检查必需字段
        required_fields = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
        missing_fields = []
        
        for field in required_fields:
            if field not in first_item:
                missing_fields.append(field)
        
        if missing_fields:
            print(f"\n❌ 缺少必需字段: {missing_fields}")
            return False
        else:
            print(f"\n✅ 必需字段完整: {required_fields}")
        
        # 检查时间戳
        if 'timestamp' in first_item and 'timestamp' in last_item:
            try:
                first_time = datetime.fromtimestamp(first_item['timestamp'] / 1000)
                last_time = datetime.fromtimestamp(last_item['timestamp'] / 1000)
                time_span = last_time - first_time
                
                print(f"\n📅 时间范围:")
                print(f"  开始: {first_time.strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"  结束: {last_time.strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"  跨度: {time_span}")
                
                # 检查是否是最近的数据
                now = datetime.now()
                age = now - last_time
                print(f"  数据新鲜度: {age} 前")
                
                if age.total_seconds() > 3600:  # 超过1小时
                    print(f"  ⚠️  数据可能过时（超过1小时）")
                else:
                    print(f"  ✅ 数据较新")
                
            except Exception as e:
                print(f"  ⚠️  时间戳解析失败: {e}")
        
        # 检查数据连续性（抽样检查前10条）
        print(f"\n🔍 数据连续性检查（前10条）:")
        gaps = []
        for i in range(min(9, len(data) - 1)):
            current_ts = data[i]['timestamp']
            next_ts = data[i + 1]['timestamp']
            gap = (next_ts - current_ts) / 1000 / 60  # 转换为分钟
            
            if gap > 1.5:  # 超过1.5分钟认为有间隔
                gaps.append((i, gap))
                print(f"  ⚠️  第{i}条到第{i+1}条: 间隔{gap:.1f}分钟")
        
        if not gaps:
            print(f"  ✅ 前10条数据连续")
        else:
            print(f"  ⚠️  发现{len(gaps)}个间隔")
        
        # 检查价格数据合理性
        print(f"\n💰 价格数据检查:")
        prices = []
        for item in data[:100]:  # 检查前100条
            if all(k in item for k in ['open', 'high', 'low', 'close']):
                prices.append({
                    'open': item['open'],
                    'high': item['high'],
                    'low': item['low'],
                    'close': item['close']
                })
        
        if prices:
            # 检查是否有0值
            zero_count = sum(1 for p in prices if any(v == 0 for v in p.values()))
            if zero_count > 0:
                print(f"  ⚠️  发现{zero_count}条数据包含0值")
            else:
                print(f"  ✅ 无0值数据")
            
            # 检查high >= low
            invalid_count = sum(1 for p in prices if p['high'] < p['low'])
            if invalid_count > 0:
                print(f"  ❌ 发现{invalid_count}条数据high < low（异常）")
            else:
                print(f"  ✅ high >= low 检查通过")
            
            # 检查价格范围
            all_prices = []
            for p in prices:
                all_prices.extend([p['open'], p['high'], p['low'], p['close']])
            
            if all_prices:
                min_price = min(all_prices)
                max_price = max(all_prices)
                print(f"  价格范围: {min_price:.8f} ~ {max_price:.8f}")
        
        return True
        
    except json.JSONDecodeError as e:
        print(f"❌ JSON解析失败: {e}")
        print(f"  文件可能损坏或格式错误")
        return False
    except Exception as e:
        print(f"❌ 检查失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def check_all_klines():
    """检查所有模型的K线数据"""
    models = ['qwen', 'deepseek']
    symbols = ['BTC/USDT:USDT', 'ETH/USDT:USDT', 'SOL/USDT:USDT', 
               'BNB/USDT:USDT', 'XRP/USDT:USDT', 'DOGE/USDT:USDT', 'LTC/USDT:USDT']
    
    print(f"\n🔍 K线数据完整性检查工具")
    print(f"运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    results = {}
    
    for model in models:
        results[model] = {}
        for symbol in symbols:
            results[model][symbol] = check_kline_file(model, symbol)
    
    # 总结
    print(f"\n{'='*60}")
    print(f"检查总结")
    print(f"{'='*60}")
    
    for model in models:
        print(f"\n{model.upper()}:")
        ok_count = sum(1 for v in results[model].values() if v)
        total_count = len(results[model])
        print(f"  正常: {ok_count}/{total_count}")
        
        if ok_count < total_count:
            print(f"  异常币种:")
            for symbol, ok in results[model].items():
                if not ok:
                    print(f"    - {symbol}")
    
    # 建议
    print(f"\n{'='*60}")
    print(f"📝 诊断建议")
    print(f"{'='*60}")
    
    all_ok = all(all(v for v in results[model].values()) for model in models)
    
    if all_ok:
        print("✅ 所有K线数据正常")
        print("\n如果前端仍然看不到K线图，可能的原因：")
        print("1. 前端缓存问题（清除浏览器缓存）")
        print("2. 前端API请求失败（检查浏览器控制台）")
        print("3. 前端K线组件渲染问题（检查前端日志）")
    else:
        print("⚠️  发现数据问题")
        print("\n建议：")
        print("1. 检查系统运行日志，查看K线数据获取是否有错误")
        print("2. 手动触发一次数据更新")
        print("3. 检查币安API是否正常")
        print("4. 检查网络连接")
    
    print(f"\n{'='*60}")
    print(f"🔧 手动修复命令")
    print(f"{'='*60}")
    print("如果数据异常，可以尝试：")
    print("1. 删除异常文件并重新获取：")
    print("   rm /root/10-23-bot/ds/trading_data/*/kline_data/*_1m.json")
    print("2. 重启服务触发数据更新：")
    print("   supervisorctl restart ai-bot:*")

if __name__ == "__main__":
    check_all_klines()

