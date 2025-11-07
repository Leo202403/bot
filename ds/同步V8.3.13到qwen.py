#!/usr/bin/env python3
"""同步V8.3.13的所有新增函数到qwen"""

# 读取文件
with open('deepseek_多币种智能版.py', 'r', encoding='utf-8') as f:
    deepseek_lines = f.readlines()

with open('qwen_多币种智能版.py', 'r', encoding='utf-8') as f:
    qwen_lines = f.readlines()

# 找到deepseek中V8.3.13函数的起止位置
ds_start = None
ds_end = None

for i, line in enumerate(deepseek_lines):
    if 'def get_pattern_based_tp_sl(entry_price' in line:
        ds_start = i
        print(f"✓ 找到get_pattern_based_tp_sl在行{i+1}")
    elif ds_start and 'def analyze_missed_opportunities(trends, actual_trades, config):' in line:
        ds_end = i
        print(f"✓ 找到analyze_missed_opportunities在行{i+1}")
        break

if not ds_start or not ds_end:
    print("❌ 找不到起止位置")
    exit(1)

print(f"✓ V8.3.13代码段: 行{ds_start+1}到行{ds_end}，共{ds_end-ds_start}行")

# 找到qwen中对应的插入位置（detect_engulfing之后）
qw_insert_pos = None

for i, line in enumerate(qwen_lines):
    if 'def detect_breakout_candle(curr_ohlc, prev_high, avg_volume):' in line:
        qw_insert_pos = i
        print(f"✓ 找到qwen插入位置在行{i+1}")
        break

if not qw_insert_pos:
    print("❌ 找不到qwen插入位置")
    exit(1)

# 插入新代码
new_qwen_lines = (
    qwen_lines[:qw_insert_pos] +
    deepseek_lines[ds_start:ds_end] +
    ['\n'] +
    qwen_lines[qw_insert_pos:]
)

# 写回
with open('qwen_多币种智能版.py', 'w', encoding='utf-8') as f:
    f.writelines(new_qwen_lines)

print(f"✅ 已同步{ds_end-ds_start}行V8.3.13代码到qwen")
print(f"✅ 新qwen文件行数: {len(new_qwen_lines)}")
