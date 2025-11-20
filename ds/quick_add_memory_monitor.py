"""
快速添加内存监控 - 只在关键OOM点添加
V8.5.2.4.89.2

这个脚本只在已知的OOM高危点添加监控，最小化修改。
"""

import sys
import shutil
from pathlib import Path


def add_monitoring_to_file(file_path: str):
    """在文件中添加内存监控（只在关键点）"""
    
    print(f"\n处理文件: {file_path}")
    print("=" * 60)
    
    # 备份
    backup_path = f"{file_path}.monitor_backup"
    shutil.copy2(file_path, backup_path)
    print(f"✓ 已备份到: {backup_path}")
    
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    # 检测是否已经集成
    if any('from memory_monitor import' in line for line in lines):
        print("⚠️ 文件已包含memory_monitor导入，跳过")
        return
    
    # 要插入的位置和代码
    insertions = []
    
    # 1. 导入语句（在import os之后）
    for i, line in enumerate(lines):
        if line.strip().startswith('import os') and i < 50:
            insertions.append((
                i + 1,
                '\n# 【V8.5.2.4.89.2】内存监控（仅关键OOM点）\n'
                'try:\n'
                '    from memory_monitor import init_global_monitor, memory_checkpoint\n'
                '    _mem_monitor_available = True\n'
                'except ImportError:\n'
                '    _mem_monitor_available = False\n'
                '    def memory_checkpoint(*args, **kwargs): pass\n'
                '    def init_global_monitor(*args, **kwargs): return None\n\n'
            ))
            break
    
    # 2. 初始化（在manual_backtest开始处）
    for i, line in enumerate(lines):
        if 'manual_backtest = os.getenv("MANUAL_BACKTEST")' in line:
            # 找到下一个if manual_backtest:
            for j in range(i, min(i + 20, len(lines))):
                if 'if manual_backtest:' in lines[j]:
                    insertions.append((
                        j + 1,
                        '    # 【V8.5.2.4.89.2】初始化内存监控\n'
                        '    if _mem_monitor_available:\n'
                        '        from datetime import datetime\n'
                        '        _monitor = init_global_monitor(\n'
                        '            name=f"backtest_{datetime.now().strftime(\'%Y%m%d_%H%M%S\')}",\n'
                        '            log_file=f"memory_monitor_{datetime.now().strftime(\'%Y%m%d_%H%M%S\')}.log",\n'
                        '            warning_threshold_mb=800,\n'
                        '            critical_threshold_mb=950\n'
                        '        )\n'
                        '        memory_checkpoint("回测启动")\n'
                        '    \n'
                    ))
                    break
            break
    
    # 3. 关键OOM点监控
    oom_points = [
        # Phase 1结束
        ('print("  ✅ 客观机会识别完成', '    memory_checkpoint("Phase1_END")\n'),
        
        # Phase 2结束
        ('print("✅ 选择第', '    memory_checkpoint("Phase2_END")\n'),
        
        # Phase 3粗筛开始
        ('print("     ⚡ 【第一阶段：粗筛】', '        memory_checkpoint("Phase3_粗筛_START")\n'),
        
        # Phase 3精选开始
        ('print("     🔬 【第二阶段：精选】', '        memory_checkpoint("Phase3_精选_START")\n'),
        
        # Phase 3结束
        ('print("  ✅ Phase 3优化完成', '    memory_checkpoint("Phase3_END")\n'),
        
        # Phase 4结束
        ('print("  ✅ Phase 4验证通过', '    memory_checkpoint("Phase4_END")\n'),
        
        # 🔥 关键OOM点1：参数变化检测
        ('print("[参数变化检测] config_changed = True")', 
         '    memory_checkpoint("参数变化检测_BEFORE")\n',
         'BEFORE'),
        ('print("[参数变化检测] config_changed = True")', 
         '    memory_checkpoint("参数变化检测_AFTER")\n',
         'AFTER'),
        
        # 🔥 关键OOM点2：加载config
        ('config = load_learning_config()',
         '            memory_checkpoint("加载config_BEFORE")\n',
         'BEFORE'),
        ('config = load_learning_config()',
         '            memory_checkpoint("加载config_AFTER", f"config keys={list(config.keys())}")\n',
         'AFTER'),
        
        # 🔥 关键OOM点3：创建old_config
        ("old_config = {",
         '            memory_checkpoint("创建old_config_BEFORE")\n',
         'BEFORE'),
        ("'swing_params': copy.deepcopy(config.get('swing_params', {}))",
         '            memory_checkpoint("创建old_config_AFTER")\n',
         'AFTER'),
        
        # 收集Phase数据
        ('print("[V8.5.2.4.81] 收集Phase数据', '    memory_checkpoint("收集Phase数据_START")\n'),
        
        # 机会对比分析
        ('print("  📊 [V8.5.2.4.47] 生成机会对比分析', '    memory_checkpoint("机会对比分析_START")\n'),
        
        # 邮件生成
        ('print("📧 生成邮件主题', '    memory_checkpoint("邮件生成_START")\n'),
        ('print("✅ 邮件发送成功', '    memory_checkpoint("邮件发送完成")\n'),
        
        # 程序结束
        ('print("[Bark推送] 推送完成', 
         '    memory_checkpoint("程序结束")\n'
         '    if _mem_monitor_available and _monitor:\n'
         '        print("\\n" + "=" * 60)\n'
         '        print(_monitor.generate_report())\n'
         '        print("=" * 60 + "\\n")\n'),
    ]
    
    for pattern_tuple in oom_points:
        if len(pattern_tuple) == 2:
            pattern, code = pattern_tuple
            position = 'AFTER'
        else:
            pattern, code, position = pattern_tuple
        
        for i, line in enumerate(lines):
            if pattern in line:
                if position == 'BEFORE':
                    insertions.append((i, code))
                else:  # AFTER
                    insertions.append((i + 1, code))
                break
    
    # 按行号排序（倒序，这样插入时不会影响后面的行号）
    insertions.sort(key=lambda x: x[0], reverse=True)
    
    # 插入代码
    for line_num, code in insertions:
        lines.insert(line_num, code)
    
    # 写回文件
    with open(file_path, 'w', encoding='utf-8') as f:
        f.writelines(lines)
    
    print(f"✓ 已添加 {len(insertions)} 个监控点")
    print(f"✓ 完成！")


def main():
    print("=" * 60)
    print("快速添加内存监控工具 V8.5.2.4.89.2")
    print("=" * 60)
    print()
    print("说明：")
    print("  1. 只在已知的OOM高危点添加监控")
    print("  2. 最小化修改，不改变代码逻辑")
    print("  3. 自动备份原文件（*.monitor_backup）")
    print("  4. 如果没有psutil，会自动降级为空操作")
    print()
    
    # 处理文件
    files = [
        "deepseek_多币种智能版.py",
        "qwen_多币种智能版.py"
    ]
    
    for file_name in files:
        file_path = Path(__file__).parent / file_name
        if file_path.exists():
            try:
                add_monitoring_to_file(str(file_path))
            except Exception as e:
                print(f"❌ 处理失败: {e}")
                import traceback
                traceback.print_exc()
        else:
            print(f"⚠️ 文件不存在: {file_path}")
    
    print()
    print("=" * 60)
    print("✅ 集成完成！")
    print()
    print("下一步：")
    print("  1. 确保已安装psutil: pip3 install psutil")
    print("  2. 运行回测: MANUAL_BACKTEST=true python3 deepseek_多币种智能版.py backtest-deepseek")
    print("  3. 如果Killed，查看: tail -100 memory_monitor_*.log")
    print("  4. 最后一个checkpoint即为OOM位置")
    print()
    print("如需还原：")
    print("  mv deepseek_多币种智能版.py.monitor_backup deepseek_多币种智能版.py")
    print("=" * 60)


if __name__ == "__main__":
    main()

