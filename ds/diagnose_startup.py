#!/usr/bin/env python3
"""DeepSeek启动诊断脚本"""
import sys
from pathlib import Path

print("=" * 60)
print("DeepSeek启动诊断")
print("=" * 60)

# 1. 检查.env文件
print("\n1. 检查.env文件:")
env_file = Path(__file__).parent / '.env'
env_deepseek = Path(__file__).parent / '.env.deepseek'
env_qwen = Path(__file__).parent / '.env.qwen'

print(f"   .env 存在: {env_file.exists()}")
print(f"   .env.deepseek 存在: {env_deepseek.exists()}")
print(f"   .env.qwen 存在: {env_qwen.exists()}")

if env_file.exists():
    print(f"   .env 大小: {env_file.stat().st_size} bytes")
    
# 2. 尝试加载环境变量
print("\n2. 尝试加载环境变量:")
try:
    from dotenv import load_dotenv
    import os
    
    # 尝试加载.env
    if env_file.exists():
        load_dotenv(env_file, override=True)
        print("   ✓ .env 加载成功")
        
        # 检查关键变量
        api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("API_KEY")
        if api_key:
            print(f"   ✓ API密钥已设置 (长度: {len(api_key)})")
        else:
            print("   ✗ 未找到API密钥（DEEPSEEK_API_KEY或API_KEY）")
    else:
        print("   ✗ .env 文件不存在")
except Exception as e:
    print(f"   ✗ 加载失败: {e}")

# 3. 尝试导入主模块
print("\n3. 尝试导入主模块:")
try:
    sys.path.insert(0, str(Path(__file__).parent))
    # 只导入，不执行
    import deepseek_多币种智能版
    print("   ✓ 模块导入成功")
except FileNotFoundError as e:
    print(f"   ✗ 文件未找到: {e}")
except ValueError as e:
    print(f"   ✗ 配置错误: {e}")
except Exception as e:
    print(f"   ✗ 导入失败: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
print("诊断完成")
print("=" * 60)
