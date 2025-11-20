#!/usr/bin/env python3
"""
批量检测和报告所有缩进错误
"""
import ast
import sys

def check_syntax(filename):
    """检查Python文件语法并报告所有错误"""
    print(f"检查文件: {filename}")
    
    try:
        with open(filename, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 尝试编译
        compile(content, filename, 'exec')
        print(f"✅ {filename} 语法正确！")
        return True
        
    except SyntaxError as e:
        print(f"\n❌ 语法错误:")
        print(f"   文件: {e.filename}")
        print(f"   行号: {e.lineno}")
        print(f"   偏移: {e.offset}")
        print(f"   错误: {e.msg}")
        if e.text:
            print(f"   代码: {e.text.rstrip()}")
        return False
    except Exception as e:
        print(f"❌ 其他错误: {e}")
        return False

if __name__ == "__main__":
    files = [
        "deepseek_多币种智能版.py",
        "qwen_多币种智能版.py"
    ]
    
    all_ok = True
    for f in files:
        if not check_syntax(f):
            all_ok = False
            print()
    
    if all_ok:
        print("\n🎉 所有文件语法正确！")
        sys.exit(0)
    else:
        print("\n⚠️ 存在语法错误，请修复")
        sys.exit(1)

