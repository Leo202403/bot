#!/usr/bin/env python3
"""
V8.9.1.1 启动诊断脚本
用于排查代码无限重启的问题
"""

import sys
import os
import traceback

print("=" * 70)
print("🔍 V8.9.1.1 启动诊断")
print("=" * 70)

# 1. 检查Python版本
print(f"\n1️⃣ Python版本: {sys.version}")

# 2. 检查工作目录
print(f"\n2️⃣ 当前目录: {os.getcwd()}")

# 3. 检查prompt_optimizer模块
print(f"\n3️⃣ 检查prompt_optimizer模块...")
try:
    import prompt_optimizer
    print("   ✅ prompt_optimizer导入成功")
    
    # 检查函数是否存在
    if hasattr(prompt_optimizer, 'check_deterministic_exit'):
        print("   ✅ check_deterministic_exit函数存在")
    else:
        print("   ❌ check_deterministic_exit函数不存在！")
    
    if hasattr(prompt_optimizer, 'build_reversal_check_prompt'):
        print("   ✅ build_reversal_check_prompt函数存在")
    else:
        print("   ❌ build_reversal_check_prompt函数不存在！")
        
except Exception as e:
    print(f"   ❌ prompt_optimizer导入失败: {e}")
    traceback.print_exc()

# 4. 检查qwen文件语法
print(f"\n4️⃣ 检查qwen文件语法...")
try:
    import py_compile
    py_compile.compile('qwen_多币种智能版.py', doraise=True)
    print("   ✅ qwen文件语法正确")
except Exception as e:
    print(f"   ❌ qwen文件语法错误: {e}")
    traceback.print_exc()

# 5. 尝试导入qwen模块（不执行main）
print(f"\n5️⃣ 尝试导入qwen模块...")
try:
    # 临时设置环境变量，防止自动执行
    os.environ['SKIP_MAIN'] = 'true'
    
    # 使用importlib导入，不执行__main__
    import importlib.util
    spec = importlib.util.spec_from_file_location("qwen_module", "qwen_多币种智能版.py")
    if spec and spec.loader:
        module = importlib.util.module_from_spec(spec)
        # 不执行main，只加载模块
        print("   ⚠️ 跳过模块执行（模块包含立即执行代码）")
    
    print("   ✅ qwen模块结构正常")
except Exception as e:
    print(f"   ❌ qwen模块导入失败: {e}")
    traceback.print_exc()

# 6. 检查关键依赖
print(f"\n6️⃣ 检查关键依赖...")
dependencies = {
    'ccxt': 'CCXT交易所库',
    'openai': 'OpenAI API',
    'pydantic': 'Pydantic数据验证',
    'schedule': 'Schedule定时任务',
}

for dep, desc in dependencies.items():
    try:
        __import__(dep)
        print(f"   ✅ {desc} ({dep})")
    except ImportError:
        print(f"   ❌ {desc} ({dep}) - 未安装")

# 7. 检查环境变量
print(f"\n7️⃣ 检查环境变量...")
required_vars = ['QWEN_API_KEY', 'BINANCE_APIKEY', 'BINANCE_SECRET']
for var in required_vars:
    if os.getenv(var):
        print(f"   ✅ {var} 已设置")
    else:
        print(f"   ⚠️ {var} 未设置")

# 8. 检查V8.9.1.1新增代码的关键点
print(f"\n8️⃣ 检查V8.9.1.1关键代码...")
try:
    with open('qwen_多币种智能版.py', 'r', encoding='utf-8') as f:
        content = f.read()
        
    # 检查关键点
    checks = {
        'deterministic_exit_symbols': 'deterministic_exit_symbols变量',
        'from prompt_optimizer import check_deterministic_exit': '确定性EXIT导入',
        'from prompt_optimizer import build_reversal_check_prompt': '反转检查导入',
        'V8.9.1.1': '版本标记',
    }
    
    for key, desc in checks.items():
        if key in content:
            print(f"   ✅ {desc}")
        else:
            print(f"   ⚠️ {desc} - 未找到")
            
except Exception as e:
    print(f"   ❌ 文件检查失败: {e}")

# 9. 模拟trading_bot执行的前几步
print(f"\n9️⃣ 模拟trading_bot初始化...")
try:
    print("   [1] 导入prompt_optimizer...")
    from prompt_optimizer import check_deterministic_exit
    print("   ✅ check_deterministic_exit导入成功")
    
    print("   [2] 测试check_deterministic_exit函数...")
    # 模拟测试
    test_position = {
        'symbol': 'BTC/USDT:USDT',
        'side': 'LONG',
        'entry_price': 100000,
        'take_profit_price': 102000,
        'stop_loss_price': 99000,
        'signal_type': 'scalping',
        'open_time': '2025-01-01 00:00:00',
    }
    test_price = 100500
    should_exit, reason = check_deterministic_exit(test_position, test_price)
    print(f"   ✅ 函数执行成功: should_exit={should_exit}, reason={reason}")
    
except Exception as e:
    print(f"   ❌ 模拟执行失败: {e}")
    traceback.print_exc()

print("\n" + "=" * 70)
print("🎯 诊断完成！请检查上述输出，找出❌标记的问题")
print("=" * 70)

print("\n📝 建议排查步骤：")
print("1. 如果prompt_optimizer导入失败 → 检查文件是否存在")
print("2. 如果语法错误 → 运行 python3 -m py_compile qwen_多币种智能版.py")
print("3. 如果依赖缺失 → pip install <缺失的包>")
print("4. 如果环境变量未设置 → 检查.env文件或系统环境变量")
print("5. 查看完整错误日志 → 检查是否有Python traceback")
