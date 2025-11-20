#!/usr/bin/env python3
"""自动修复所有缩进错误"""
import re

file_path = "ds/deepseek_多币种智能版.py"

with open(file_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# 找出所有需要修复的行号
issues = []
for i in range(len(lines)):
    line = lines[i]
    # 检查重复的else
    if i > 0 and line.strip().startswith('else:'):
        prev_line = lines[i-1]
        if prev_line.strip().startswith('else:') or 'else:' in prev_line:
            issues.append((i+1, "duplicate else"))
    
    # 检查缩进突然增加超过4个空格
    if i > 0:
        curr_indent = len(line) - len(line.lstrip())
        prev_indent = len(lines[i-1]) - len(lines[i-1].lstrip())
        if curr_indent > prev_indent + 8 and line.strip():
            issues.append((i+1, f"indent jump {prev_indent}->{curr_indent}"))

print(f"发现 {len(issues)} 个潜在问题：")
for line_no, issue in issues[:10]:
    print(f"  行{line_no}: {issue}")
