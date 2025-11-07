#!/usr/bin/env python3
"""精确同步V8.3.13 - 按函数单独复制"""

import re

# 读取文件
with open('deepseek_多币种智能版.py', 'r', encoding='utf-8') as f:
    ds_content = f.read()

with open('qwen_多币种智能版.py', 'r', encoding='utf-8') as f:
    qw_content = f.read()

# 定义要复制的函数（按顺序）
functions_to_copy = [
    ('get_pattern_based_tp_sl', 'def detect_breakout_candle'),
    ('_simulate_trade_with_params_enhanced', 'def _simulate_trade_with_params('),
    ('analyze_per_symbol_opportunities', 'def analyze_missed_opportunities'),
    ('optimize_per_symbol_params', None),
    ('get_per_symbol_params', None),
    ('analyze_multi_timeframe_exits', None),
    ('generate_timeframe_recommendations', None),
    ('select_strategy_by_market_state', None),
    ('class TradingEnvironment', None),
    ('class ParameterAgent', None),
]

print("开始精确同步...")

# 1. 提取deepseek中的所有目标函数
extracted_funcs = {}

for func_name, _ in functions_to_copy:
    # 找函数定义
    if func_name.startswith('class'):
        pattern = rf'^{re.escape(func_name)}:.*?(?=\n(?:def |class |\Z))'
    else:
        pattern = rf'^def {re.escape(func_name)}\(.*?(?=\ndef |\nclass |\Z)'
    
    match = re.search(pattern, ds_content, re.MULTILINE | re.DOTALL)
    if match:
        extracted_funcs[func_name] = match.group(0)
        print(f"✓ 提取 {func_name}: {len(match.group(0))}字符")
    else:
        print(f"❌ 未找到 {func_name}")

# 2. 在qwen中找到插入位置并插入
qw_lines = qw_content.split('\n')

# 插入get_pattern_based_tp_sl（在detect_breakout_candle之前）
if 'get_pattern_based_tp_sl' in extracted_funcs:
    insert_idx = None
    for i, line in enumerate(qw_lines):
        if 'def detect_breakout_candle(curr_ohlc, prev_high, avg_volume):' in line:
            insert_idx = i
            break
    
    if insert_idx:
        func_text = extracted_funcs['get_pattern_based_tp_sl']
        func_lines = func_text.split('\n')
        qw_lines = qw_lines[:insert_idx] + func_lines + [''] + qw_lines[insert_idx:]
        print(f"✓ 插入 get_pattern_based_tp_sl 在行 {insert_idx}")

# 插入_simulate_trade_with_params_enhanced（在_simulate_trade_with_params之前）
if '_simulate_trade_with_params_enhanced' in extracted_funcs:
    insert_idx = None
    for i, line in enumerate(qw_lines):
        if line.startswith('def _simulate_trade_with_params(entry_price'):
            insert_idx = i
            break
    
    if insert_idx:
        func_text = extracted_funcs['_simulate_trade_with_params_enhanced']
        func_lines = func_text.split('\n')
        qw_lines = qw_lines[:insert_idx] + func_lines + ['', ''] + qw_lines[insert_idx:]
        print(f"✓ 插入 _simulate_trade_with_params_enhanced 在行 {insert_idx}")

# 插入Per-Symbol和其他函数（在analyze_missed_opportunities之前）
remaining_funcs = [
    'analyze_per_symbol_opportunities',
    'optimize_per_symbol_params',
    'get_per_symbol_params',
    'analyze_multi_timeframe_exits',
    'generate_timeframe_recommendations',
    'select_strategy_by_market_state',
    'class TradingEnvironment',
    'class ParameterAgent'
]

insert_idx = None
for i, line in enumerate(qw_lines):
    if 'def analyze_missed_opportunities(trends, actual_trades, config):' in line:
        insert_idx = i
        break

if insert_idx:
    all_lines = []
    all_lines.append('# ==================================================')
    all_lines.append('# 【V8.3.13.3】Per-Symbol优化')
    all_lines.append('# ==================================================')
    all_lines.append('')
    
    for func_name in remaining_funcs:
        if func_name in extracted_funcs:
            func_lines = extracted_funcs[func_name].split('\n')
            all_lines.extend(func_lines)
            all_lines.append('')
            all_lines.append('')
    
    qw_lines = qw_lines[:insert_idx] + all_lines + qw_lines[insert_idx:]
    print(f"✓ 插入剩余函数在行 {insert_idx}")

# 写回
new_content = '\n'.join(qw_lines)
with open('qwen_多币种智能版.py', 'w', encoding='utf-8') as f:
    f.write(new_content)

print(f"\n✅ 同步完成！")
print(f"新qwen文件行数: {len(qw_lines)}")
