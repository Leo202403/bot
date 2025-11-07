#!/usr/bin/env python3
"""同步修改的优化函数到qwen"""

# 读取deepseek文件
with open('deepseek_多币种智能版.py', 'r', encoding='utf-8') as f:
    deepseek_lines = f.readlines()

# 读取qwen文件
with open('qwen_多币种智能版.py', 'r', encoding='utf-8') as f:
    qwen_lines = f.readlines()

# 找到deepseek中两个优化函数的起止位置
ds_scalping_start = None
ds_scalping_end = None
ds_swing_start = None
ds_swing_end = None

for i, line in enumerate(deepseek_lines):
    if 'def optimize_scalping_params(scalping_data, current_params):' in line:
        ds_scalping_start = i
    elif ds_scalping_start and 'def optimize_swing_params(swing_data, current_params):' in line:
        ds_scalping_end = i
        ds_swing_start = i
    elif ds_swing_start and 'def analyze_missed_opportunities(trends, actual_trades, config):' in line:
        ds_swing_end = i
        break

print(f"✓ Deepseek: scalping {ds_scalping_start+1}-{ds_scalping_end}, swing {ds_swing_start+1}-{ds_swing_end}")

# 找到qwen中两个优化函数的起止位置
qw_scalping_start = None
qw_swing_start = None
qw_swing_end = None

for i, line in enumerate(qwen_lines):
    if 'def optimize_scalping_params(scalping_data, current_params):' in line:
        qw_scalping_start = i
    elif 'def optimize_swing_params(swing_data, current_params):' in line:
        qw_swing_start = i
    elif qw_swing_start and 'def analyze_missed_opportunities(trends, actual_trades, config):' in line:
        qw_swing_end = i
        break

print(f"✓ Qwen: scalping start {qw_scalping_start+1}, swing {qw_swing_start+1}-{qw_swing_end}")

# 替换两个函数
new_qwen_lines = (
    qwen_lines[:qw_scalping_start] +
    deepseek_lines[ds_scalping_start:ds_swing_end] +
    ['\n'] +
    qwen_lines[qw_swing_end:]
)

# 写回
with open('qwen_多币种智能版.py', 'w', encoding='utf-8') as f:
    f.writelines(new_qwen_lines)

print(f"✅ 已同步两个优化函数到qwen")
print(f"✅ 新qwen行数: {len(new_qwen_lines)}")
