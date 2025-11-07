#!/usr/bin/env python3
"""
修复unexpected indent错误（过度缩进）
"""
import subprocess
import re

def find_and_fix_unexpected_indents(filepath):
    """找到并修复所有unexpected indent错误"""
    fixes_count = 0
    
    while True:
        # 运行py_compile检查语法
        result = subprocess.run(
            ['python3', '-m', 'py_compile', filepath],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0:
            print(f"✅ {filepath}: 所有unexpected indent已修复！")
            break
        
        # 从错误信息中提取行号
        error_output = result.stderr
        match = re.search(r'IndentationError: unexpected indent \(.*?, line (\d+)\)', error_output)
        
        if not match:
            print(f"⚠️ 发现其他错误（非unexpected indent）:")
            print(error_output[:500])
            break
        
        line_num = int(match.group(1))
        print(f"修复第{line_num}行的unexpected indent...")
        
        # 读取文件
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        # 修复该行：减少缩进直到与上一行同级或减少4个空格
        if line_num > 0 and line_num <= len(lines):
            problem_line = lines[line_num - 1]
            problem_indent = len(problem_line) - len(problem_line.lstrip())
            
            # 查找上一个非空行
            prev_line_idx = line_num - 2
            while prev_line_idx >= 0 and not lines[prev_line_idx].strip():
                prev_line_idx -= 1
            
            if prev_line_idx >= 0:
                prev_line = lines[prev_line_idx]
                prev_indent = len(prev_line) - len(prev_line.lstrip())
                
                # 如果当前行缩进比上一行多超过4个空格，减少到+4
                # 或者如果当前行缩进比上一行少但仍然过多，对齐到同级
                if problem_indent > prev_indent + 4:
                    # 减少缩进到prev_indent + 4
                    new_indent = prev_indent + 4
                    lines[line_num - 1] = ' ' * new_indent + problem_line.lstrip()
                    fixes_count += 1
                elif problem_indent > prev_indent and problem_indent < prev_indent + 4:
                    # 对齐到同级
                    lines[line_num - 1] = ' ' * prev_indent + problem_line.lstrip()
                    fixes_count += 1
                else:
                    # 尝试减少4个空格
                    new_indent = max(0, problem_indent - 4)
                    lines[line_num - 1] = ' ' * new_indent + problem_line.lstrip()
                    fixes_count += 1
            else:
                # 减少4个空格
                new_indent = max(0, problem_indent - 4)
                lines[line_num - 1] = ' ' * new_indent + problem_line.lstrip()
                fixes_count += 1
            
            # 写回文件
            with open(filepath, 'w', encoding='utf-8') as f:
                f.writelines(lines)
        else:
            print(f"❌ 行号 {line_num} 超出文件范围")
            break
        
        # 防止无限循环
        if fixes_count > 100:
            print(f"⚠️ 已修复{fixes_count}处，可能存在其他问题")
            break
    
    return fixes_count

if __name__ == '__main__':
    files = ['qwen_多币种智能版.py', 'deepseek_多币种智能版.py']
    total_fixes = 0
    
    for filepath in files:
        try:
            print(f"\n处理 {filepath}...")
            fixes = find_and_fix_unexpected_indents(filepath)
            total_fixes += fixes
            print(f"  修复了 {fixes} 处unexpected indent")
        except Exception as e:
            print(f"❌ 处理 {filepath} 时出错: {e}")
    
    print(f"\n🎉 总共修复了 {total_fixes} 处unexpected indent错误")

