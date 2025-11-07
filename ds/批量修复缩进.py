#!/usr/bin/env python3
"""
批量修复Python文件中的常见缩进错误
"""
import re
import sys

def fix_indentation_errors(filepath):
    """修复文件中的缩进错误"""
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    fixed_lines = []
    i = 0
    fixes_count = 0
    
    while i < len(lines):
        line = lines[i]
        
        # 获取当前行的缩进级别
        current_stripped = line.lstrip()
        current_indent = len(line) - len(current_stripped)
        
        # 检查是否是控制结构（try, if, elif, else, for, while, with, def, class等）
        control_keywords = ['try:', 'if ', 'elif ', 'else:', 'for ', 'while ', 'with ', 'def ', 'class ', 'except ', 'finally:']
        is_control = any(current_stripped.startswith(kw) or (':' in current_stripped and kw.strip(':') in current_stripped) for kw in control_keywords)
        
        if is_control and i + 1 < len(lines):
            next_line = lines[i + 1]
            next_stripped = next_line.lstrip()
            next_indent = len(next_line) - len(next_stripped)
            
            # 跳过空行和注释
            if next_stripped and not next_stripped.startswith('#'):
                # 检查是否是except/finally/elif/else（它们应该和try/if同级）
                next_is_same_level = any(next_stripped.startswith(kw) for kw in ['except ', 'finally:', 'elif ', 'else:'])
                
                if not next_is_same_level:
                    # 下一行应该比当前行多缩进4个空格
                    expected_indent = current_indent + 4
                    
                    if next_indent < expected_indent:
                        # 需要增加缩进
                        indent_diff = expected_indent - next_indent
                        fixed_next_line = (' ' * expected_indent) + next_stripped
                        fixed_lines.append(line)
                        fixed_lines.append(fixed_next_line)
                        fixes_count += 1
                        print(f"修复第{i+2}行缩进: {next_stripped[:50]}...")
                        i += 2
                        continue
        
        fixed_lines.append(line)
        i += 1
    
    # 写回文件
    with open(filepath, 'w', encoding='utf-8') as f:
        f.writelines(fixed_lines)
    
    print(f"\n✅ {filepath}: 修复了 {fixes_count} 处缩进错误")
    return fixes_count

if __name__ == '__main__':
    files = ['qwen_多币种智能版.py', 'deepseek_多币种智能版.py']
    total_fixes = 0
    
    for filepath in files:
        try:
            fixes = fix_indentation_errors(filepath)
            total_fixes += fixes
        except Exception as e:
            print(f"❌ 处理 {filepath} 时出错: {e}")
    
    print(f"\n🎉 总共修复了 {total_fixes} 处缩进错误")
    print("\n建议：运行 python3 -m py_compile 验证语法")

