#!/usr/bin/env python3
"""同步V8.3.12.1的Exit Analysis相关函数到qwen文件"""

# 读取deepseek文件
with open('deepseek_多币种智能版.py', 'r', encoding='utf-8') as f:
    deepseek_lines = f.readlines()

# 读取qwen文件
with open('qwen_多币种智能版.py', 'r', encoding='utf-8') as f:
    qwen_lines = f.readlines()

# 找到calculate_scalping_score在qwen中的位置
qwen_scalping_score_line = None
for i, line in enumerate(qwen_lines):
    if 'def calculate_scalping_score(sim_result):' in line:
        qwen_scalping_score_line = i
        break

if qwen_scalping_score_line is None:
    print("❌ 找不到calculate_scalping_score")
    exit(1)

print(f"✓ 找到qwen中calculate_scalping_score在行{qwen_scalping_score_line + 1}")

# 找到deepseek中simulate_params_on_opportunities_with_details的开始行
deepseek_start_line = None
for i, line in enumerate(deepseek_lines):
    if 'def simulate_params_on_opportunities_with_details(opportunities, params):' in line:
        deepseek_start_line = i
        break

if deepseek_start_line is None:
    print("❌ 找不到simulate_params_on_opportunities_with_details")
    exit(1)

print(f"✓ 找到deepseek中新增函数在行{deepseek_start_line + 1}")

# 提取新增的函数（从simulate_params_on_opportunities_with_details到calculate_scalping_score之前）
deepseek_end_line = None
for i in range(deepseek_start_line + 1, len(deepseek_lines)):
    if 'def calculate_scalping_score(sim_result):' in deepseek_lines[i]:
        deepseek_end_line = i
        break

if deepseek_end_line is None:
    print("❌ 找不到结束位置")
    exit(1)

print(f"✓ 新增内容从行{deepseek_start_line + 1}到行{deepseek_end_line}，共{deepseek_end_line - deepseek_start_line}行")

# 插入新内容到qwen
new_qwen_lines = (
    qwen_lines[:qwen_scalping_score_line] +
    deepseek_lines[deepseek_start_line:deepseek_end_line] +
    ['\n'] +
    qwen_lines[qwen_scalping_score_line:]
)

# 写回qwen文件
with open('qwen_多币种智能版.py', 'w', encoding='utf-8') as f:
    f.writelines(new_qwen_lines)

print(f"✅ 已同步{deepseek_end_line - deepseek_start_line}行新代码到qwen")
print(f"✅ 新的qwen文件行数: {len(new_qwen_lines)}")
