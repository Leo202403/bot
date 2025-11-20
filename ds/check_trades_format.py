#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
检查trades_history.csv的格式问题
"""

import csv
from pathlib import Path


def check_trades_format(model_name):
    """检查指定模型的交易记录格式"""
    print(f"\n{'='*60}")
    print(f"📋 检查 {model_name.upper()} 交易记录格式")
    print(f"{'='*60}")
    
    trades_file = Path(__file__).parent / "trading_data" / model_name / "trades_history.csv"
    
    if not trades_file.exists():
        print(f"❌ 文件不存在: {trades_file}")
        return
    
    try:
        with open(trades_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            
            if not fieldnames:
                print("❌ 无法读取字段名（文件可能为空）")
                return
            
            # 显示字段信息
            print(f"\n📌 字段信息:")
            print(f"  字段数: {len(fieldnames)}")
            print(f"  字段列表:")
            for i, field in enumerate(fieldnames, 1):
                field_display = repr(field)  # 显示隐藏字符
                print(f"    {i:2d}. {field_display:50s} (长度: {len(field)})")
            
            # 读取所有记录
            trades = list(reader)
            total = len(trades)
            
            print(f"\n📊 记录统计:")
            print(f"  总记录数: {total}")
            
            if total == 0:
                print("  ⚠️  文件中没有交易记录")
                return
            
            # 检查最后几条记录
            print(f"\n🔍 检查最后5条记录:")
            
            for idx, trade in enumerate(trades[-5:], start=max(1, total-4)):
                print(f"\n  【记录 #{idx}】")
                
                # 检查字段数量
                actual_fields = len([k for k in trade.keys()])
                if actual_fields != len(fieldnames):
                    print(f"    ⚠️  字段数不匹配: 期望{len(fieldnames)}, 实际{actual_fields}")
                
                # 检查关键字段
                key_fields = ['币种', '方向', '开仓时间', '平仓时间', '数量', '开仓价格']
                missing_fields = []
                empty_fields = []
                
                for field in key_fields:
                    # 尝试精确匹配
                    value = trade.get(field)
                    if value is None:
                        # 尝试找相似字段
                        similar = [f for f in fieldnames if field in f or f.strip() == field]
                        if similar:
                            value = trade.get(similar[0])
                            if value is None:
                                missing_fields.append(f"{field} (找到相似: {similar[0]})")
                        else:
                            missing_fields.append(field)
                    
                    if value is not None:
                        if isinstance(value, str) and not value.strip():
                            if field not in ['平仓时间', '平仓价格']:  # 这两个可以为空
                                empty_fields.append(field)
                
                # 显示关键信息
                coin = trade.get('币种', trade.get('symbol', 'N/A'))
                direction = trade.get('方向', trade.get('direction', 'N/A'))
                open_time = trade.get('开仓时间', 'N/A')
                close_time = trade.get('平仓时间', '')
                quantity = trade.get('数量', 'N/A')
                
                print(f"    币种: {coin}")
                print(f"    方向: {direction}")
                print(f"    开仓时间: {open_time}")
                print(f"    平仓时间: {close_time if close_time else '(未平仓)'}")
                print(f"    数量: {quantity}")
                
                if missing_fields:
                    print(f"    ❌ 缺失字段: {', '.join(missing_fields)}")
                
                if empty_fields:
                    print(f"    ⚠️  空值字段: {', '.join(empty_fields)}")
                
                # 检查字段值长度异常
                for field, value in trade.items():
                    if value and len(str(value)) > 500:
                        print(f"    ⚠️  字段过长: {field} (长度: {len(str(value))})")
            
            # 统计未平仓订单
            open_trades = [t for t in trades if not t.get('平仓时间', '').strip()]
            print(f"\n📈 未平仓订单: {len(open_trades)} 笔")
            
            if open_trades:
                print(f"  详情:")
                for t in open_trades:
                    coin = t.get('币种', 'N/A')
                    direction = t.get('方向', 'N/A')
                    open_time = t.get('开仓时间', 'N/A')
                    print(f"    - {coin} {direction} (开仓: {open_time})")
            
            # 检查是否有重复记录
            print(f"\n🔄 检查重复记录:")
            seen = {}
            duplicates = []
            
            for idx, trade in enumerate(trades):
                key = f"{trade.get('币种', '')}_{trade.get('方向', '')}_{trade.get('开仓时间', '')}"
                if key in seen:
                    duplicates.append((seen[key], idx))
                else:
                    seen[key] = idx
            
            if duplicates:
                print(f"  ⚠️  发现 {len(duplicates)} 组重复记录:")
                for orig_idx, dup_idx in duplicates[:5]:
                    print(f"    记录 #{orig_idx+1} 和 #{dup_idx+1} 重复")
            else:
                print(f"  ✓ 没有重复记录")
            
            # 尝试读取后端可能的错误
            print(f"\n🧪 模拟后端读取:")
            try:
                # 尝试转换数值字段
                for trade in trades[-3:]:
                    try:
                        pnl_str = trade.get('盈亏(U)', '0')
                        if pnl_str and pnl_str.strip():
                            pnl = float(pnl_str)
                    except Exception as e:
                        print(f"  ❌ 盈亏字段转换失败: {e}")
                        print(f"     记录: {trade.get('币种')} {trade.get('方向')}")
                        print(f"     盈亏值: {repr(trade.get('盈亏(U)'))}")
                
                print(f"  ✓ 后端读取模拟通过")
            except Exception as e:
                print(f"  ❌ 后端读取可能失败: {e}")
        
        print(f"\n{'='*60}")
        print(f"✅ {model_name.upper()} 检查完成")
        print(f"{'='*60}")
        
    except Exception as e:
        print(f"\n❌ 检查失败: {e}")
        import traceback
        traceback.print_exc()


def main():
    """主函数"""
    print("="*60)
    print("🔍 trades_history.csv 格式检查工具")
    print("="*60)
    
    # 检查两个模型
    for model in ['deepseek', 'qwen']:
        check_trades_format(model)
    
    print("\n" + "="*60)
    print("💡 修复建议")
    print("="*60)
    
    print("""
如果发现格式问题：

1. 字段数不匹配
   → 恢复的订单字段数与CSV表头不一致
   → 解决: 删除问题记录或从备份恢复

2. 关键字段为空
   → 币种、方向、开仓时间等必需字段为空
   → 解决: 手动补充或删除该记录

3. 字段名有空格或特殊字符
   → 字段名包含不可见字符
   → 解决: 重新生成CSV表头

4. 重复记录
   → 同一持仓被多次添加
   → 解决: 删除重复记录

快速修复命令:
  cd /root/10-23-bot/ds
  
  # 从备份恢复
  cp data_backup/20251120_160156/trades_history.csv trading_data/deepseek/
  
  # 或删除最后N行
  head -n -1 trading_data/deepseek/trades_history.csv > temp.csv
  mv temp.csv trading_data/deepseek/trades_history.csv
    """)


if __name__ == "__main__":
    main()

