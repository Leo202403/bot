"""
集成内存监控到现有回测代码
V8.5.2.4.89.2

用法：
python3 integrate_memory_monitor.py

这个脚本会自动在回测代码的关键位置插入内存监控检查点
"""

import re
import sys
from pathlib import Path


def integrate_to_file(file_path: str, backup: bool = True):
    """将内存监控集成到指定文件"""
    
    print(f"正在处理: {file_path}")
    
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 备份原文件
    if backup:
        backup_path = f"{file_path}.backup"
        with open(backup_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"  ✓ 已备份到: {backup_path}")
    
    # 检查是否已经集成过
    if 'from memory_monitor import' in content:
        print(f"  ⚠️ 文件已集成内存监控，跳过")
        return
    
    # 在imports后添加memory_monitor导入
    import_pattern = r'(import os\nimport sys.*?\n)'
    import_addition = (
        r'\1'
        '# 【V8.5.2.4.89.2】集成内存监控\n'
        'from memory_monitor import init_global_monitor, memory_checkpoint, memory_context, get_global_monitor\n\n'
    )
    content = re.sub(import_pattern, import_addition, content, count=1, flags=re.DOTALL)
    
    # 在main函数开始处初始化监控器
    main_pattern = r'(if __name__ == .__main__.:.*?\n)'
    main_addition = (
        r'\1'
        '    # 【V8.5.2.4.89.2】初始化内存监控\n'
        '    bot_name = sys.argv[1] if len(sys.argv) > 1 else "unknown"\n'
        '    memory_monitor = init_global_monitor(\n'
        '        name=f"{bot_name}_backtest",\n'
        '        log_file=f"memory_monitor_{bot_name}_{datetime.now().strftime(\'%Y%m%d_%H%M%S\')}.log",\n'
        '        warning_threshold_mb=800,\n'
        '        critical_threshold_mb=950\n'
        '    )\n'
        '    memory_checkpoint("程序启动")\n\n'
    )
    content = re.sub(main_pattern, main_addition, content, count=1, flags=re.DOTALL)
    
    # 在关键位置添加检查点
    checkpoints = [
        # Phase 1
        (r'(print\("【Phase 1: 客观机会识别】"\))', r'\1\n    memory_checkpoint("Phase1_START")'),
        (r'(print\("  ✅ 自适应分类完成.*?\n)', r'\1    memory_checkpoint("Phase1_分类完成")'),
        (r'(print\("  ✅ 客观机会识别完成.*?\n)', r'\1    memory_checkpoint("Phase1_END")'),
        
        # 错过机会分析
        (r'(print\("【错过机会分析】"\))', r'\1\n    memory_checkpoint("错过机会分析_START")'),
        (r'(print\("ℹ️  跳过旧版错过机会分析.*?\n)', r'\1    memory_checkpoint("错过机会分析_END")'),
        
        # Phase 2
        (r'(print\("【第2步：多轮迭代参数优化】"\))', r'\1\n    memory_checkpoint("Phase2_START")'),
        (r'(save_learning_config\(config\).*?# .*?Phase 2)', r'memory_checkpoint("Phase2_保存前")\n    \1\n    memory_checkpoint("Phase2_保存后")'),
        
        # Phase 3
        (r'(print\("【🚀 Phase 3启动】"\))', r'\1\n    memory_checkpoint("Phase3_START")'),
        (r'(print\("     ⚡ 【第一阶段：粗筛】.*?\n)', r'\1        memory_checkpoint("Phase3_粗筛_START")'),
        (r'(print\("     🏆 粗筛Top2起点.*?\n)', r'\1        memory_checkpoint("Phase3_粗筛_END")'),
        (r'(print\("     🔬 【第二阶段：精选】.*?\n)', r'\1        memory_checkpoint("Phase3_精选_START")'),
        (r'(print\("     🏆 最终最佳起点.*?\n)', r'\1        memory_checkpoint("Phase3_精选_END")'),
        (r'(print\("  📊 【分离优化】.*?\n)', r'\1    memory_checkpoint("Phase3_分离优化_START")'),
        (r'(print\("  ✅ Phase 3优化完成.*?\n)', r'\1    memory_checkpoint("Phase3_END")'),
        
        # Phase 4
        (r'(print\("【✅ Phase 4：参数验证与过拟合检测】"\))', r'\1\n    memory_checkpoint("Phase4_START")'),
        (r'(print\("  ✅ Phase 4验证通过.*?\n)', r'\1    memory_checkpoint("Phase4_END")'),
        
        # 参数变化检测（关键OOM点）
        (r'(print\("\[参数变化检测\] config_changed = True"\))', r'memory_checkpoint("参数变化检测_BEFORE")\n    \1\n    memory_checkpoint("参数变化检测_AFTER")'),
        
        # 加载config（关键OOM点）
        (r'(config = load_learning_config\(\).*?# .*?V8\.5\.2\.4\.89)', r'memory_checkpoint("加载config_BEFORE")\n    \1\n    memory_checkpoint("加载config_AFTER", f"config大小={sys.getsizeof(config)}")'),
        
        # 创建old_config（关键OOM点）
        (r'(old_config = \{.*?# .*?V8\.5\.2\.4\.89\.1)', r'memory_checkpoint("创建old_config_BEFORE")\n    \1\n    memory_checkpoint("创建old_config_AFTER", f"old_config大小={sys.getsizeof(old_config)}")'),
        
        # 收集Phase数据
        (r'(print\("\[V8\.5\.2\.4\.81\] 收集Phase数据.*?\n)', r'\1    memory_checkpoint("收集Phase数据_START")'),
        
        # 生成机会对比
        (r'(print\("  📊 \[V8\.5\.2\.4\.47\] 生成机会对比分析.*?\n)', r'\1    memory_checkpoint("机会对比分析_START")'),
        
        # 邮件生成
        (r'(print\("📧 生成邮件主题.*?\n)', r'memory_checkpoint("邮件生成_START")\n    \1'),
        (r'(print\("✅ 邮件发送成功.*?\n)', r'\1    memory_checkpoint("邮件生成_END")'),
        
        # 程序结束
        (r'(print\("\[Bark推送\] 推送完成.*?\n)', r'\1    memory_checkpoint("程序结束")\n    \n    # 生成内存监控报告\n    if memory_monitor:\n        report = memory_monitor.generate_report()\n        print("\\n" + report)'),
    ]
    
    for pattern, replacement in checkpoints:
        content = re.sub(pattern, replacement, content, flags=re.DOTALL)
    
    # 写回文件
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"  ✓ 已集成内存监控检查点")


def main():
    # 集成到两个主文件
    files = [
        "deepseek_多币种智能版.py",
        "qwen_多币种智能版.py"
    ]
    
    print("=" * 80)
    print("内存监控集成工具 V8.5.2.4.89.2")
    print("=" * 80)
    print()
    
    for file_name in files:
        file_path = Path(__file__).parent / file_name
        if file_path.exists():
            try:
                integrate_to_file(str(file_path), backup=True)
            except Exception as e:
                print(f"  ❌ 集成失败: {e}")
                import traceback
                traceback.print_exc()
        else:
            print(f"⚠️ 文件不存在: {file_path}")
        print()
    
    print("=" * 80)
    print("✅ 集成完成！")
    print()
    print("现在可以运行回测，内存监控会自动记录到日志文件：")
    print("  memory_monitor_<bot_name>_<timestamp>.log")
    print()
    print("如果遇到OOM，查看日志找到最后一个检查点即可定位问题位置")
    print("=" * 80)


if __name__ == "__main__":
    main()

