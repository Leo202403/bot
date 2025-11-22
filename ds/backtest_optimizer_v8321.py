#!/usr/bin/env python3
"""【V8.3.21】回测优化模块 - 轻量级、成本优化、资源控制

特性：
1. 多维度Grid Search（11个参数维度）
2. V8.3.21上下文过滤（K线/市场结构/S/R历史）
3. 本地统计分析（参数敏感度、异常检测）
4. 成本优化的AI决策（压缩数据、精简Prompt）
5. 资源控制（限制内存、CPU nice值、进程隔离）

适用环境：2核2G服务器
"""

import gc
import os
import random

import numpy as np

# 尝试导入psutil（可选）
try:
    import psutil

    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False


# ============================================================
# 【步骤2】轻量级Grid Search（资源控制）
# ============================================================


def optimize_params_v8321_lightweight(
    opportunities: list[dict],
    current_params: dict,
    signal_type: str = "scalping",
    max_combinations: int = 200,
    ai_suggested_params: dict | None = None,
) -> dict:
    """【V8.3.21】轻量级参数优化

    设计：
    - 2核CPU：使用随机采样代替遍历（200组 vs 2592组）
    - 2G内存：及时释放内存，每10组GC一次
    - 进程隔离：设置nice值，避免影响实时AI

    Args:
        opportunities: 机会列表（已包含V8.3.21字段）
        current_params: 当前参数
        signal_type: 'scalping' or 'swing'
        max_combinations: 最大测试组数（默认200）
        ai_suggested_params: 【V8.3.25.10新增】AI洞察建议的参数（将加入测试候选集）

    Returns:
        {
            'optimized_params': {...},
            'top_10_configs': [...],
            'statistics': {...},
            'cost_saved': 0.xx
        }

    """
    # 设置进程优先级（nice值=10，避免影响实时AI）
    try:
        os.nice(10)
        print("   ℹ️  已设置进程优先级（nice=10），避免影响实时AI")
    except (OSError, AttributeError):
        pass

    print(f"\n{'=' * 60}")
    print(f"【V8.3.21回测优化】轻量级参数搜索（{signal_type}）")
    print(f"  机会数: {len(opportunities)}")
    print(f"  测试组数: {max_combinations}")
    if HAS_PSUTIL:
        print(
            f"  内存限制: 检测到{psutil.virtual_memory().total / (1024**3):.1f}G，将主动控制"
        )
    else:
        print("  资源监控: 不可用（psutil未安装）")
    print(f"{'=' * 60}\n")

    # ===== 阶段1：定义搜索空间 =====
    print("📊 阶段1: 定义搜索空间...")

    # 【V8.4.4】传入current_params作为baseline，允许动态调整搜索中心
    param_grid = define_param_grid_v8321(signal_type, baseline_params=current_params)
    total_combinations = calculate_total_combinations(param_grid)

    print("   ✅ 搜索空间定义完成")
    print(f"      理论组合数: {total_combinations}组")
    print(f"      实际测试数: {max_combinations}组（随机采样）")

    # ===== 阶段2：随机采样Grid Search =====
    print("\n🔍 阶段2: 随机采样Grid Search...")

    sampled_params = random_sample_param_grid(param_grid, max_combinations)

    # 【V8.3.25.10】将AI建议的参数加入测试候选集
    if ai_suggested_params:
        print("   🤖 发现AI建议参数，加入测试候选集...")
        ai_config = {}
        # 🔧 V8.3.25.12: 只保留搜索空间中存在的参数
        valid_param_names = set(param_grid.keys())
        for key, value in ai_suggested_params.items():
            if key in valid_param_names:
                ai_config[key] = value
            else:
                print(f"      ⚠️  跳过不在搜索空间中的参数: {key}={value}")

        if ai_config:
            # 确保AI建议的参数在候选集的前列（优先测试）
            sampled_params.insert(0, ai_config)
            print(f"      ✅ AI建议参数已加入（优先测试）: {ai_config}")
        else:
            print("      ℹ️  AI建议的参数都不在搜索空间中，跳过")

    all_results = []

    for i, params in enumerate(sampled_params):
        # 内存检查（每10组检查一次）
        if i % 10 == 0 and HAS_PSUTIL:
            mem_usage = psutil.Process().memory_info().rss / (1024**2)
            if mem_usage > 300:  # 超过300MB则GC
                gc.collect()
                print(f"      [{i}/{max_combinations}] 内存: {mem_usage:.0f}MB → GC")

        # 模拟这个参数配置
        result = simulate_params_with_v8321_filter(opportunities, params)
        score = calculate_v8321_optimization_score(result)

        all_results.append({
            "params": params,
            "score": score,
            "metrics": extract_key_metrics(result),
        })

        # 进度显示
        if (i + 1) % 20 == 0:
            print(f"      进度: {i + 1}/{max_combinations}...")

    # 排序并取Top 10
    top_10 = sorted(all_results, key=lambda x: x["score"], reverse=True)[:10]

    print("   ✅ Grid Search完成")
    print(f"      最高分: {top_10[0]['score']:.3f}")
    print(f"      测试组数: {len(all_results)}")

    # 主动GC
    gc.collect()

    # ===== 阶段3：本地统计分析 =====
    print("\n📈 阶段3: 本地统计分析（免费）...")

    # 本地计算：参数敏感度
    param_sensitivity = calculate_param_sensitivity_local(all_results)

    # 本地计算：上下文特征相关性
    context_analysis = analyze_context_features_local(
        opportunities, top_10[0]["params"]
    )

    # 本地检测：异常情况
    anomalies = detect_anomalies_local(all_results, param_sensitivity)

    print("   ✅ 统计分析完成")
    print(f"      关键参数: {list(param_sensitivity.keys())[:3]}")
    print(f"      异常检测: {len(anomalies)}个")

    # ===== 阶段4：数据压缩 =====
    print("\n🗜️  阶段4: 数据压缩（节省AI成本）...")

    compressed_data = compress_optimization_results(
        top_10=top_10,
        param_sensitivity=param_sensitivity,
        context_analysis=context_analysis,
        anomalies=anomalies,
    )

    estimated_tokens = estimate_token_count(compressed_data)
    original_tokens = len(all_results) * 100  # 假设原始每组100 tokens
    cost_saved = (original_tokens - estimated_tokens) * 0.00002  # GPT-4价格

    print("   ✅ 数据压缩完成")
    print(f"      原始: ~{original_tokens} tokens")
    print(f"      压缩后: ~{estimated_tokens} tokens")
    print(f"      💰 预计节省: ${cost_saved:.4f}")

    # ===== 阶段5：AI迭代决策（可选）=====
    ai_decision = None
    ai_adjusted_params = None

    if max_combinations >= 100:  # 只有大规模搜索才值得AI介入
        print("\n🤖 阶段5: AI迭代决策...")
        try:
            ai_decision = call_ai_for_iterative_optimization(
                top_10_configs=top_10,
                param_sensitivity=param_sensitivity,
                context_analysis=context_analysis,
                anomalies=anomalies,
                compressed_data=compressed_data,
                signal_type=signal_type,
            )

            if ai_decision and ai_decision.get("needs_adjustment"):
                print("   🔧 AI建议调整参数...")
                ai_adjusted_params = apply_ai_adjustments(
                    base_params=top_10[0]["params"],
                    adjustments=ai_decision["param_adjustments"],
                )

                # 验证AI调整后的参数
                ai_result = simulate_params_with_v8321_filter(
                    opportunities, ai_adjusted_params
                )
                ai_score = calculate_v8321_optimization_score(ai_result)

                print("   📊 AI调整效果:")
                print(f"      Grid最优: {top_10[0]['score']:.3f}")
                print(
                    f"      AI调整后: {ai_score:.3f} ({ai_score - top_10[0]['score']:+.3f})"
                )

                # 如果AI调整后更好，使用AI参数
                if ai_score > top_10[0]["score"]:
                    print("   ✅ AI调整有效，采纳AI建议")
                    final_params = ai_adjusted_params
                    cost_saved += 0.01  # AI调用成本约$0.01
                else:
                    print("   ⚠️  AI调整效果不佳，保持Grid结果")
                    final_params = top_10[0]["params"]
                    top_10[0]["score"]
            else:
                print("   ✅ AI认为当前参数已是最优")
                final_params = top_10[0]["params"]
                top_10[0]["score"]

        except Exception as e:
            print(f"   ⚠️  AI决策失败: {e}")
            final_params = top_10[0]["params"]
            top_10[0]["score"]
    else:
        final_params = top_10[0]["params"]
        top_10[0]["score"]

    return {
        "optimized_params": final_params,
        "top_10_configs": top_10,
        "statistics": {
            "param_sensitivity": param_sensitivity,
            "score_distribution": calculate_score_distribution(all_results),
        },
        "context_analysis": context_analysis,
        "anomalies": anomalies,
        "compressed_data": compressed_data,
        "cost_saved": cost_saved,
        "ai_decision": ai_decision,  # AI决策（英文）
        "ai_adjusted_params": ai_adjusted_params,  # AI调整后的参数
    }


def define_param_grid_v8321(
    signal_type: str, baseline_params: dict | None = None
) -> dict:
    """【V8.4.4】定义V8.3.21参数搜索空间（动态范围约束）

    核心思路：
    1. 固定基准参数（阶段2用于计算actual_profit，确保客观性）
    2. 优化器可以在基准±50%范围内搜索（自适应市场波动）
    3. 设置绝对边界防止极端值（如atr_tp=6.0）

    示例（波段）：
    - 基准：atr_tp=3.0
    - 搜索范围：[1.5, 3.0, 4.5]（±50%）
    - 绝对边界：[2.0, 5.0]（不允许<2.0或>5.0）
    - 实际搜索：[2.0, 3.0, 4.5]

    Args:
        signal_type: 'scalping' 或 'swing'
        baseline_params: 上一次优化的参数（用于动态调整搜索中心）

    Returns:
        参数搜索空间字典

    """
    # 【V8.5.2.4.39】扩大参数搜索空间（用户反馈：扩大范围，更好地找到最优参数）
    if signal_type == "scalping":
        # 超短线固定基准
        baseline = {
            "atr_tp_multiplier": 2.0,
            "atr_stop_multiplier": 1.5,
            "max_holding_hours": 8,
            "min_risk_reward": 1.0,  # 【V8.4.7】从1.5降到1.0（匹配实际R:R分布）
        }
        # 【V8.5.2.4.39】绝对边界扩大（硬约束，但允许更广范围探索）
        bounds = {
            "atr_tp_multiplier": (0.8, 4.0),  # 扩大：1.0-3.0 → 0.8-4.0
            "atr_stop_multiplier": (0.8, 2.5),  # 扩大：1.0-2.0 → 0.8-2.5
            "max_holding_hours": (2, 24),  # 扩大：4-16 → 2-24
            "min_risk_reward": (0.5, 3.5),  # 扩大：0.5-2.5 → 0.5-3.5
        }
    else:  # swing
        # 波段固定基准
        baseline = {
            "atr_tp_multiplier": 3.0,
            "atr_stop_multiplier": 1.5,
            "max_holding_hours": 60,
            "min_risk_reward": 1.2,  # 【V8.4.7】从1.5降到1.2（更接近实际）
        }
        # 【V8.5.2.4.39】绝对边界扩大
        bounds = {
            "atr_tp_multiplier": (1.5, 7.0),  # 扩大：2.0-5.0 → 1.5-7.0
            "atr_stop_multiplier": (0.8, 3.0),  # 扩大：1.0-2.5 → 0.8-3.0
            "max_holding_hours": (24, 120),  # 扩大：36-96 → 24-120
            "min_risk_reward": (0.5, 4.0),  # 扩大：0.5-3.0 → 0.5-4.0
        }

    # 【V8.4.4】如果提供了baseline_params，用它作为搜索中心（但仍受边界限制）
    if baseline_params:
        for key in [
            "atr_tp_multiplier",
            "atr_stop_multiplier",
            "max_holding_hours",
            "min_risk_reward",
        ]:
            if key in baseline_params:
                value = baseline_params[key]
                min_bound, max_bound = bounds[key]
                # 限制在边界内
                baseline[key] = max(min_bound, min(max_bound, value))

    # 【V8.4.4】生成搜索空间（基准±50%，受绝对边界限制）
    def generate_search_range(param_name, center_value):
        """生成搜索范围：center ± 50%，但不超过绝对边界"""
        min_bound, max_bound = bounds[param_name]

        # 计算±50%范围
        lower = max(min_bound, center_value * 0.5)
        upper = min(max_bound, center_value * 1.5)

        # 生成3个采样点：下限、中心、上限
        if param_name == "max_holding_hours":
            # 整数参数
            return [int(lower), int(center_value), int(upper)]
        # 浮点参数，保留1位小数
        return [round(lower, 1), round(center_value, 1), round(upper, 1)]

    if signal_type == "scalping":
        grid = {
            # 【V8.4.4】基础参数（动态范围，围绕基准±50%）
            "max_holding_hours": generate_search_range(
                "max_holding_hours", baseline["max_holding_hours"]
            ),
            "atr_tp_multiplier": generate_search_range(
                "atr_tp_multiplier", baseline["atr_tp_multiplier"]
            ),
            "atr_stop_multiplier": generate_search_range(
                "atr_stop_multiplier", baseline["atr_stop_multiplier"]
            ),
            "min_risk_reward": generate_search_range(
                "min_risk_reward", baseline["min_risk_reward"]
            ),
            # 入场过滤参数（保持原有范围）
            "min_signal_score": [40, 50, 60],
            "min_consensus_score": [0, 10, 20, 30],
            "min_consensus": [0, 1, 2],
            "min_kline_bullish_ratio": [0.6, 0.7],
            "min_price_chg_pct": [0.5, 1.0, 1.5],
            "allowed_mkt_struct": ["all", "trend_only"],
            "min_trend_age_hours": [0.5, 1.0],
            "max_sr_test_count": [5, 999],
        }
    else:  # swing
        grid = {
            # 【V8.4.4】基础参数（动态范围，围绕基准±50%）
            "max_holding_hours": generate_search_range(
                "max_holding_hours", baseline["max_holding_hours"]
            ),
            "atr_tp_multiplier": generate_search_range(
                "atr_tp_multiplier", baseline["atr_tp_multiplier"]
            ),
            "atr_stop_multiplier": generate_search_range(
                "atr_stop_multiplier", baseline["atr_stop_multiplier"]
            ),
            "min_risk_reward": generate_search_range(
                "min_risk_reward", baseline["min_risk_reward"]
            ),
            # 入场过滤参数（保持原有范围）
            "min_signal_score": [40, 50, 60],
            "min_consensus_score": [0, 10, 20, 30],
            "min_consensus": [0, 1, 2],
            "min_kline_bullish_ratio": [0.6, 0.7],
            "min_price_chg_pct": [0.5, 1.0, 1.5],
            "allowed_mkt_struct": ["all", "trend_only"],
            "min_trend_age_hours": [1.0, 2.0],
            "max_sr_test_count": [5, 999],
        }

    return grid


def random_sample_param_grid(grid: dict, sample_size: int) -> list[dict]:
    """【V8.4.5】智能采样参数组合

    策略：
    1. 边界采样（30%）：测试每个参数的极值，确保覆盖边界
    2. 中心点采样（1个）：测试默认配置
    3. 随机填充（剩余）：覆盖其他区域

    优势：
    - 确保测试所有关键区域（边界、中心）
    - 不增加计算量（仍然200组）
    - 提高找到最优解的概率

    示例（200组）：
    - 边界采样：60组（每个参数的min/max配置）
    - 中心点：1组
    - 随机：139组
    """
    samples = []
    param_names = list(grid.keys())
    param_values = [grid[name] for name in param_names]

    # ===== 1. 边界采样（30%） =====
    boundary_samples = []
    for i, param_name in enumerate(param_names):
        values = param_values[i]
        if len(values) < 2:
            continue  # 只有1个值，跳过

        # 最小值配置：该参数取最小值，其他参数取中间值
        min_config = {}
        for j, name in enumerate(param_names):
            if j == i:
                min_config[name] = param_values[j][0]  # 最小值
            else:
                mid_idx = len(param_values[j]) // 2
                min_config[name] = param_values[j][mid_idx]  # 中间值
        boundary_samples.append(min_config)

        # 最大值配置：该参数取最大值，其他参数取中间值
        max_config = {}
        for j, name in enumerate(param_names):
            if j == i:
                max_config[name] = param_values[j][-1]  # 最大值
            else:
                mid_idx = len(param_values[j]) // 2
                max_config[name] = param_values[j][mid_idx]  # 中间值
        boundary_samples.append(max_config)

    # 去重（可能有重复的边界配置）
    boundary_samples_unique = []
    seen = set()
    for config in boundary_samples:
        config_tuple = tuple(sorted(config.items()))
        if config_tuple not in seen:
            seen.add(config_tuple)
            boundary_samples_unique.append(config)

    samples.extend(boundary_samples_unique)

    # ===== 2. 中心点采样（1个） =====
    center_config = {}
    for i, name in enumerate(param_names):
        mid_idx = len(param_values[i]) // 2
        center_config[name] = param_values[i][mid_idx]

    # 检查是否已存在
    center_tuple = tuple(sorted(center_config.items()))
    if center_tuple not in seen:
        samples.append(center_config)
        seen.add(center_tuple)

    # ===== 3. 随机填充（剩余） =====
    remaining = sample_size - len(samples)
    if remaining > 0:
        # 生成所有组合的索引
        from itertools import product

        all_indices = list(product(*[range(len(vals)) for vals in param_values]))

        # 过滤掉已采样的配置
        available_indices = []
        for indices in all_indices:
            config = {
                param_names[i]: param_values[i][indices[i]]
                for i in range(len(param_names))
            }
            config_tuple = tuple(sorted(config.items()))
            if config_tuple not in seen:
                available_indices.append(indices)

        # 随机采样
        if len(available_indices) > remaining:
            sampled_indices = random.sample(available_indices, remaining)
        else:
            sampled_indices = available_indices

        # 构建参数字典
        for indices in sampled_indices:
            config = {
                param_names[i]: param_values[i][indices[i]]
                for i in range(len(param_names))
            }
            samples.append(config)

    print("   📊 智能采样统计:")
    print(f"      边界采样: {len(boundary_samples_unique)}组")
    print("      中心点: 1组")
    print(f"      随机填充: {len(samples) - len(boundary_samples_unique) - 1}组")
    print(f"      总计: {len(samples)}组")

    return samples


def calculate_total_combinations(grid: dict) -> int:
    """计算总组合数"""
    total = 1
    for values in grid.values():
        total *= len(values)
    return total


# ============================================================
# 【步骤3】V8.3.21上下文过滤函数
# ============================================================


def test_params_on_opportunities(opportunities: list[dict], params: dict) -> dict:
    """【V8.4.5】测试参数在机会集上的表现（别名函数）

    这是simulate_params_with_v8321_filter的别名，
    用于前向验证时测试参数效果。

    Args:
        opportunities: 机会列表
        params: 参数字典

    Returns:
        统计结果字典（包括avg_profit, capture_rate等）

    """
    return simulate_params_with_v8321_filter(opportunities, params)


def simulate_params_with_v8321_filter(opportunities: list[dict], params: dict) -> dict:
    """【V8.3.21→V8.3.21.1】使用上下文过滤参数模拟交易（修复过度过滤）

    过滤层次：
    1. 基础过滤（signal_score/consensus/risk_reward）- 必须
    2. K线上下文过滤（阳线比例、价格变化）- 可选
    3. 市场结构过滤（swing类型、趋势年龄）- 可选
    4. S/R历史过滤（测试次数、假突破）- 可选

    【V8.3.21.1修复】：Layer 2-4默认不启用，避免过度过滤历史数据
    """
    captured = []
    missed_reasons: dict[str, int] = {}

    # 【V8.3.21.1修复】高级过滤器默认不启用
    enable_advanced_filters = params.get("enable_advanced_filters", False)

    for opp in opportunities:
        # 第1层：基础过滤（必须）
        if not passes_basic_filter(opp, params):
            reason = "basic_params"
            missed_reasons[reason] = missed_reasons.get(reason, 0) + 1
            continue

        # 【V8.3.21.1修复】第2-4层：高级过滤（可选，默认不启用）
        if enable_advanced_filters:
            # 第2层：K线上下文过滤
            if not passes_kline_context_filter(opp, params):
                reason = "kline_context"
                missed_reasons[reason] = missed_reasons.get(reason, 0) + 1
                continue

            # 第3层：市场结构过滤
            if not passes_market_structure_filter(opp, params):
                reason = "market_structure"
                missed_reasons[reason] = missed_reasons.get(reason, 0) + 1
                continue

            # 第4层：S/R历史过滤
            if not passes_sr_history_filter(opp, params):
                reason = "sr_history"
                missed_reasons[reason] = missed_reasons.get(reason, 0) + 1
                continue

        # 通过所有过滤，记录
        captured.append(opp)

    # 计算统计指标
    if len(captured) == 0:
        return {
            "total_opportunities": len(opportunities),
            "captured_count": 0,
            "capture_rate": 0,
            "avg_profit": 0,
            "win_rate": 0,
            "time_exit_rate": 0,
            "missed_reasons": missed_reasons,
        }

    # 【V8.3.21.1修复】计算利润（兼容不同字段名）
    # 优先使用actual_profit_pct，如果没有则使用objective_profit
    profits = []
    for c in captured:
        if "actual_profit_pct" in c:
            profits.append(c["actual_profit_pct"])
        elif "objective_profit" in c:
            profits.append(c["objective_profit"])
        else:
            profits.append(0)  # 默认值

    avg_profit = np.mean(profits) if len(profits) > 0 else 0

    # 【V8.3.21风控】分离盈利和亏损
    wins = [p for p in profits if p > 0]
    losses = [p for p in profits if p <= 0]

    win_rate = len(wins) / len(profits) if len(profits) > 0 else 0
    avg_win = np.mean(wins) if len(wins) > 0 else 0
    avg_loss = np.mean(losses) if len(losses) > 0 else 0

    # 盈亏比（赚的时候赚多少 / 亏的时候亏多少）
    profit_loss_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 999

    # 期望收益（考虑胜率和盈亏比）
    expectancy = (win_rate * avg_win) + ((1 - win_rate) * avg_loss)

    # 最大回撤（连续亏损的最大值）
    max_drawdown = 0
    cumulative = 0
    peak = 0
    for p in profits:
        cumulative += p
        peak = max(peak, cumulative)
        drawdown = peak - cumulative
        max_drawdown = max(max_drawdown, drawdown)

    return {
        "total_opportunities": len(opportunities),
        "captured_count": len(captured),
        "capture_rate": len(captured) / len(opportunities),
        "avg_profit": avg_profit,
        "win_rate": win_rate,
        "time_exit_rate": 0.5,  # 简化：假设50% time_exit
        "missed_reasons": missed_reasons,
        "captured_details": captured,  # 详细数据（用于进一步分析）
        # 【V8.3.21风控】新增风控指标
        "avg_win": avg_win,  # 盈利时平均赚多少
        "avg_loss": avg_loss,  # 亏损时平均亏多少
        "profit_loss_ratio": profit_loss_ratio,  # 盈亏比
        "expectancy": expectancy,  # 期望收益
        "max_drawdown": max_drawdown,  # 最大回撤
        "win_count": len(wins),  # 盈利笔数
        "loss_count": len(losses),  # 亏损笔数
    }


def get_profit_pct(opp: dict) -> float:
    """【V8.3.21.1辅助】获取利润百分比（兼容不同字段名）

    优先级：actual_profit_pct > objective_profit > 0
    """
    if "actual_profit_pct" in opp:
        return opp["actual_profit_pct"]
    if "objective_profit" in opp:
        return opp["objective_profit"]
    return 0.0


def passes_basic_filter(opp: dict, params: dict) -> bool:
    """【V8.4】基础参数过滤 - 使用新的consensus_score

    优先级：
    1. 优先使用consensus_score（0-100）而非旧的consensus（0-5）
    2. 优先使用actual_risk_reward而非risk_reward
    """
    # 优先使用actual_risk_reward，如果没有则回退到risk_reward
    rr_value = opp.get("actual_risk_reward", opp.get("risk_reward", 0))

    # 【V8.4】优先使用新的consensus_score（0-100分）
    if "consensus_score" in opp and "min_consensus_score" in params:
        # 新版过滤：使用consensus_score
        return (
            opp["signal_score"] >= params.get("min_signal_score", 50)
            and opp["consensus_score"] >= params.get("min_consensus_score", 30)
            and rr_value >= params.get("min_risk_reward", 1.5)
        )
    # 【兼容性】回退到旧版过滤：使用consensus（0-5）
    consensus_value = opp.get("consensus", opp.get("indicator_consensus", 0))
    return (
        opp["signal_score"] >= params.get("min_signal_score", 50)
        and consensus_value >= params.get("min_consensus", 2)
        and rr_value >= params.get("min_risk_reward", 1.5)
    )


def passes_kline_context_filter(opp: dict, params: dict) -> bool:
    """K线上下文过滤"""
    # 检查阳线/阴线比例
    bullish_ratio = opp.get("kline_ctx_bullish_ratio", 0)
    min_ratio = params.get("min_kline_bullish_ratio", 0.6)

    if opp["direction"] == "long":
        if bullish_ratio < min_ratio:
            return False
    elif (1 - bullish_ratio) < min_ratio:
        return False

    # 检查价格变化幅度
    price_chg = abs(opp.get("kline_ctx_price_chg_pct", 0))
    if price_chg < params.get("min_price_chg_pct", 0.5):
        return False

    return True


def passes_market_structure_filter(opp: dict, params: dict) -> bool:
    """市场结构过滤"""
    # 检查是否只做趋势市场
    if params.get("allowed_mkt_struct") == "trend_only":
        swing_type = opp.get("mkt_struct_swing", "")
        if swing_type not in ["HH-HL", "LL-LH"]:
            return False

    # 检查趋势年龄
    trend_age = opp.get("mkt_struct_age_hours", 0)
    min_age = params.get("min_trend_age_hours", 0.5)
    if trend_age < min_age:
        return False

    return True


def passes_sr_history_filter(opp: dict, params: dict) -> bool:
    """S/R历史过滤"""
    # 根据方向选择对应的S/R
    if opp["direction"] == "long":
        test_cnt = opp.get("support_hist_test_cnt", 0)
        false_bd = opp.get("support_hist_false_bd", 0)
    else:
        test_cnt = opp.get("resist_hist_test_cnt", 0)
        false_bd = opp.get("resist_hist_false_bo", 0)

    # 检查测试次数
    max_test = params.get("max_sr_test_count", 999)
    if test_cnt > max_test:
        return False

    # 检查假突破（固定≤2次）
    if false_bd > 2:
        return False

    return True


# ============================================================
# 【步骤4】本地统计分析函数
# ============================================================


def calculate_param_sensitivity_local(all_results: list[dict]) -> dict:
    """【本地计算】参数敏感度分析

    计算每个参数变化时，score的平均变化量
    """
    sensitivity = {}

    # 按参数分组
    param_names = list(all_results[0]["params"].keys())

    for param_name in param_names:
        # 获取该参数的所有取值
        param_values = sorted(set([r["params"][param_name] for r in all_results]))

        if len(param_values) < 2:
            continue

        # 计算相邻取值之间的score变化
        score_changes = []
        for i in range(len(param_values) - 1):
            v1, v2 = param_values[i], param_values[i + 1]

            # 找到该参数=v1和v2的结果
            results_v1 = [r for r in all_results if r["params"][param_name] == v1]
            results_v2 = [r for r in all_results if r["params"][param_name] == v2]

            if results_v1 and results_v2:
                avg_score_v1 = np.mean([r["score"] for r in results_v1])
                avg_score_v2 = np.mean([r["score"] for r in results_v2])

                # 计算单位变化的影响
                param_change = abs(v2 - v1) if isinstance(v1, (int, float)) else 1
                score_change = (avg_score_v2 - avg_score_v1) / param_change
                score_changes.append(score_change)

        if score_changes:
            avg_impact = np.mean(score_changes)
            sensitivity[param_name] = {
                "avg_impact": round(avg_impact, 3),
                "std_impact": round(np.std(score_changes), 3),
                "importance": "high"
                if abs(avg_impact) > 0.1
                else "medium"
                if abs(avg_impact) > 0.05
                else "low",
            }

    return sensitivity


def analyze_context_features_local(
    opportunities: list[dict], best_params: dict
) -> dict:
    """【本地计算】上下文特征分析

    分析V8.3.21字段与成功的关系
    """
    # 使用最优参数模拟，区分captured和missed
    result = simulate_params_with_v8321_filter(opportunities, best_params)
    captured = result.get("captured_details", [])

    if len(captured) == 0:
        return {"error": "无捕获机会"}

    analysis = {}

    # 分析1：K线上下文
    analysis["kline_context"] = analyze_kline_context_impact(captured)

    # 分析2：市场结构
    analysis["market_structure"] = analyze_market_structure_impact(captured)

    # 分析3：S/R历史
    analysis["sr_history"] = analyze_sr_history_impact(captured)

    # 生成关键洞察
    analysis["key_insights"] = generate_insights_from_analysis(analysis)

    return analysis


def analyze_kline_context_impact(captured: list[dict]) -> dict:
    """分析K线上下文与成功率的关系"""
    # 按阳线比例分组
    groups: dict[str, list[dict]] = {"0.6-0.7": [], "0.7-0.8": [], "0.8-1.0": []}

    for opp in captured:
        ratio = opp.get("kline_ctx_bullish_ratio", 0)
        if 0.6 <= ratio < 0.7:
            groups["0.6-0.7"].append(opp)
        elif 0.7 <= ratio < 0.8:
            groups["0.7-0.8"].append(opp)
        elif 0.8 <= ratio <= 1.0:
            groups["0.8-1.0"].append(opp)

    # 计算各组统计
    result = {}
    for range_name, group in groups.items():
        if len(group) > 0:
            profits = [
                get_profit_pct(o) for o in group
            ]  # 【V8.3.21.1修复】使用辅助函数
            result[range_name] = {
                "count": len(group),
                "avg_profit": round(np.mean(profits), 1),
                "win_rate": round(len([p for p in profits if p > 0]) / len(profits), 2),
            }

    # 生成结论
    if result:
        best_range = max(result.keys(), key=lambda k: result[k]["avg_profit"])
        result["conclusion"] = (
            f"阳线比例{best_range}时效果最好（平均利润{result[best_range]['avg_profit']:.1f}%）"
        )

    return result


def analyze_market_structure_impact(captured: list[dict]) -> dict:
    """分析市场结构与成功率的关系"""
    # 按swing类型分组
    groups: dict[str, list[dict]] = {}
    for opp in captured:
        swing_type = opp.get("mkt_struct_swing", "unknown")
        if swing_type not in groups:
            groups[swing_type] = []
        groups[swing_type].append(opp)

    # 计算各组统计
    result = {}
    for swing_type, group in groups.items():
        if len(group) > 0:
            profits = [
                get_profit_pct(o) for o in group
            ]  # 【V8.3.21.1修复】使用辅助函数
            result[swing_type] = {
                "count": len(group),
                "avg_profit": round(np.mean(profits), 1),
            }

    # 生成结论
    if result:
        best_type = max(result.keys(), key=lambda k: result[k]["avg_profit"])
        result["conclusion"] = (
            f"{best_type}结构效果最好（平均利润{result[best_type]['avg_profit']:.1f}%）"
        )

    return result


def analyze_sr_history_impact(captured: list[dict]) -> dict:
    """分析S/R历史与成功率的关系"""
    # 按测试次数分组
    groups: dict[str, list[dict]] = {"1-2次": [], "3-5次": [], "5次+": []}

    for opp in captured:
        test_cnt = (
            opp.get("resist_hist_test_cnt", 0)
            if opp["direction"] == "short"
            else opp.get("support_hist_test_cnt", 0)
        )

        if 1 <= test_cnt <= 2:
            groups["1-2次"].append(opp)
        elif 3 <= test_cnt <= 5:
            groups["3-5次"].append(opp)
        elif test_cnt > 5:
            groups["5次+"].append(opp)

    # 计算各组统计
    result = {}
    for range_name, group in groups.items():
        if len(group) > 0:
            profits = [
                get_profit_pct(o) for o in group
            ]  # 【V8.3.21.1修复】使用辅助函数
            result[range_name] = {
                "count": len(group),
                "avg_profit": round(np.mean(profits), 1),
            }

    # 生成结论
    if result:
        best_range = max(result.keys(), key=lambda k: result[k]["avg_profit"])
        result["conclusion"] = (
            f"S/R测试{best_range}时效果最好（平均利润{result[best_range]['avg_profit']:.1f}%）"
        )

    return result


def generate_insights_from_analysis(analysis: dict) -> list[str]:
    """从分析中生成关键洞察"""
    insights = []

    # K线上下文洞察
    if "kline_context" in analysis and "conclusion" in analysis["kline_context"]:
        insights.append(f"💡 {analysis['kline_context']['conclusion']}")

    # 市场结构洞察
    if "market_structure" in analysis and "conclusion" in analysis["market_structure"]:
        insights.append(f"💡 {analysis['market_structure']['conclusion']}")

    # S/R历史洞察
    if "sr_history" in analysis and "conclusion" in analysis["sr_history"]:
        insights.append(f"💡 {analysis['sr_history']['conclusion']}")

    return insights


def detect_anomalies_local(
    all_results: list[dict], param_sensitivity: dict
) -> list[dict]:
    """【本地检测】异常情况

    基于规则检测异常，不需要AI
    """
    anomalies = []

    # 异常1：某个参数导致捕获率骤降
    for param_name in param_sensitivity:
        # 找到该参数的极端值
        param_results: dict[float, list[float]] = {}
        for r in all_results:
            pval = r["params"][param_name]
            if pval not in param_results:
                param_results[pval] = []
            param_results[pval].append(r["metrics"].get("capture_rate", 0))

        # 计算每个值的平均捕获率
        param_avg_capture = {k: np.mean(v) for k, v in param_results.items()}

        # 检测骤降
        values = sorted(param_avg_capture.keys())
        for i in range(len(values) - 1):
            v1, v2 = values[i], values[i + 1]
            drop = param_avg_capture[v2] - param_avg_capture[v1]

            if drop < -0.2:  # 下降超过20%
                anomalies.append({
                    "type": "capture_rate_drop",
                    "param": param_name,
                    "from_value": v1,
                    "to_value": v2,
                    "drop": round(drop, 2),
                    "severity": "high" if drop < -0.3 else "medium",
                    "description": f"{param_name}从{v1}→{v2}时，捕获率下降{abs(drop) * 100:.0f}%",
                })

    # 异常2：整体捕获率过低
    avg_capture_rate = np.mean([
        r["metrics"].get("capture_rate", 0) for r in all_results
    ])
    if avg_capture_rate < 0.3:
        anomalies.append({
            "type": "low_capture_rate",
            "value": round(avg_capture_rate, 2),
            "severity": "high",
            "description": f"整体捕获率过低（{avg_capture_rate * 100:.0f}%），参数可能过严",
        })

    return anomalies


# ============================================================
# 【步骤5】评分函数和辅助函数
# ============================================================


def calculate_v8321_optimization_score(result: dict) -> float:
    """【V8.5.2升级】多目标优化评分函数 - 平衡胜率、盈亏比、利润、风险

    核心目标：找到"胜率-盈亏比-总利润"的最优权衡点

    关键改进：
    1. 期望收益为核心（已包含胜率×盈利+败率×亏损）
    2. 盈亏比独立评估（避免极端配置）
    3. 软约束惩罚（而非硬性阈值）
    4. 回撤控制

    评分逻辑：
    - 期望收益 > 0：基础分
    - 盈亏比 ≥ 1.5：加分，< 1.5：扣分
    - 胜率 ≥ 30%：正常，< 30%：扣分
    - 最大回撤 < 20%：正常，> 20%：扣分
    - 捕获率：适当加分

    示例对比：
    - 高胜率低盈亏比（Qwen型）: 胜率75% + 盈亏比0.8 → 扣分
    - 低胜率高盈亏比（DeepSeek型）: 胜率30% + 盈亏比0.68 → 扣分
    - 平衡配置: 胜率50% + 盈亏比2.0 → 高分
    """
    if result["captured_count"] == 0:
        return 0.0

    # 提取核心指标
    result.get("avg_profit", 0)
    win_rate = result.get("win_rate", 0)
    avg_win = result.get("avg_win", 0)
    avg_loss = result.get("avg_loss", 0)
    max_drawdown = result.get("max_drawdown", 0)
    capture_rate = result.get("capture_rate", 0)

    # 计算盈亏比
    profit_loss_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 999

    # 计算期望收益
    expectancy = (win_rate * avg_win) + ((1 - win_rate) * avg_loss)

    # ========================================
    # 【核心评分】期望收益
    # ========================================
    if expectancy <= 0:
        # 负期望，给予极低分
        return max(0.01, 0.01 + (expectancy + 5) / 5 * 0.04)

    # 期望收益基础分（0-100）
    expectancy_score = min(100, expectancy * 20)  # 1%期望=20分，5%期望=100分

    # ========================================
    # 【权衡调节】盈亏比
    # ========================================
    pl_ratio_penalty = 0  # 初始化
    pl_ratio_bonus = 0  # 初始化

    if profit_loss_ratio < 1.5:
        # 盈亏比太低，扣分
        pl_ratio_penalty = (1.5 - profit_loss_ratio) * 20  # 每低0.1扣2分
    elif profit_loss_ratio >= 2.0:
        # 盈亏比优秀，加分
        pl_ratio_bonus = min(
            20, (profit_loss_ratio - 2.0) * 10
        )  # 每高0.1加1分，最多+20
    # else: 盈亏比正常（1.5-2.0），保持初始值0

    # ========================================
    # 【权衡调节】胜率
    # ========================================
    if win_rate < 0.30:
        # 胜率太低，扣分
        win_rate_penalty = (0.30 - win_rate) * 50  # 每低1%扣0.5分
    elif win_rate >= 0.60 and profit_loss_ratio < 1.5:
        # 高胜率但低盈亏比（过早止盈），扣分
        win_rate_penalty = 10  # 固定扣10分
    else:
        win_rate_penalty = 0

    # ========================================
    # 【风险控制】最大回撤
    # ========================================
    if max_drawdown > 0.20:
        # 回撤超过20%，扣分
        drawdown_penalty = (max_drawdown - 0.20) * 100  # 每超1%扣1分
    else:
        drawdown_penalty = 0

    # ========================================
    # 【捕获率】加分
    # ========================================
    capture_bonus = capture_rate * 15  # 100%捕获率+15分

    # ========================================
    # 【综合得分】
    # ========================================
    total_score = (
        expectancy_score  # 期望收益（核心）
        + pl_ratio_bonus
        - pl_ratio_penalty  # 盈亏比调节
        + -win_rate_penalty  # 胜率惩罚
        + -drawdown_penalty  # 回撤惩罚
        + capture_bonus  # 捕获率加分
    )

    return max(0, total_score / 100)  # 归一化到0-1


def extract_key_metrics(result: dict) -> dict:
    """提取关键指标（V8.5.2扩展：包含盈亏比、期望收益等）"""
    return {
        "capture_rate": result.get("capture_rate", 0),
        "avg_profit": result.get("avg_profit", 0),
        "win_rate": result.get("win_rate", 0),
        "time_exit_rate": result.get("time_exit_rate", 0),
        # V8.5.2新增：多目标权衡指标
        "avg_win": result.get("avg_win", 0),
        "avg_loss": result.get("avg_loss", 0),
        "profit_loss_ratio": result.get("profit_loss_ratio", 0),
        "expectancy": result.get("expectancy", 0),
        "max_drawdown": result.get("max_drawdown", 0),
    }


def calculate_score_distribution(all_results: list[dict]) -> dict:
    """计算分数分布"""
    scores = [r["score"] for r in all_results]
    return {
        "mean": round(np.mean(scores), 3),
        "std": round(np.std(scores), 3),
        "min": round(np.min(scores), 3),
        "max": round(np.max(scores), 3),
        "q25": round(np.percentile(scores, 25), 3),
        "q50": round(np.percentile(scores, 50), 3),
        "q75": round(np.percentile(scores, 75), 3),
    }


def compress_optimization_results(
    top_10: list[dict],
    param_sensitivity: dict,
    context_analysis: dict,
    anomalies: list[dict],
) -> dict:
    """压缩优化结果（用于AI决策）

    将详细数据压缩成摘要
    """
    return {
        "top_3_configs": [
            {
                "rank": i + 1,
                "score": r["score"],
                "params_summary": format_params_compact(r["params"]),
                "metrics": r["metrics"],
            }
            for i, r in enumerate(top_10[:3])
        ],
        "param_sensitivity_summary": {
            k: v
            for k, v in sorted(
                param_sensitivity.items(),
                key=lambda x: abs(x[1]["avg_impact"]),
                reverse=True,
            )[:5]  # 只保留Top 5
        },
        "context_insights": context_analysis.get("key_insights", []),
        "anomalies_summary": [
            {
                "type": a["type"],
                "severity": a["severity"],
                "description": a["description"],
            }
            for a in anomalies[:3]  # 只保留Top 3
        ],
    }


def format_params_compact(params: dict) -> str:
    """紧凑格式化参数"""
    return ", ".join([f"{k}={v}" for k, v in list(params.items())[:3]]) + "..."


def estimate_token_count(data: dict) -> int:
    """估算token数量"""
    import json

    json_str = json.dumps(data)
    # 粗略估算：每4个字符≈1 token
    return len(json_str) // 4


# ============================================================
# 主函数示例
# ============================================================

# ============================================================
# 【AI迭代决策层】英文通信，用于多轮优化
# ============================================================


def call_ai_for_iterative_optimization(
    top_10_configs: list[dict],
    param_sensitivity: dict,
    context_analysis: dict,
    anomalies: list[dict],
    compressed_data: dict,
    signal_type: str,
) -> dict:
    """【V8.3.21 AI迭代】Call AI for iterative parameter optimization

    Communication: English (efficient for AI)
    Output: English (internal use only, translated to Chinese for users)

    Args:
        top_10_configs: Top 10 parameter configurations from Grid Search
        param_sensitivity: Parameter sensitivity analysis
        context_analysis: Market context analysis
        anomalies: Detected anomalies
        compressed_data: Compressed optimization data
        signal_type: 'scalping' or 'swing'

    Returns:
        AI decision dict (English)

    """
    # 构建英文Prompt
    prompt = build_ai_optimization_prompt_en(
        top_10_configs=top_10_configs,
        param_sensitivity=param_sensitivity,
        context_analysis=context_analysis,
        anomalies=anomalies,
        signal_type=signal_type,
    )

    # 调用AI（英文通信）
    ai_response = call_deepseek_for_optimization(prompt)

    # 解析AI响应（英文）
    ai_decision = parse_ai_optimization_response(ai_response)

    # 转换关键洞察为中文（给用户看）
    if ai_decision:
        ai_decision["key_insights_zh"] = translate_insights_to_chinese(
            ai_decision.get("key_insights_en", [])
        )

    return ai_decision


def build_ai_optimization_prompt_en(
    top_10_configs: list[dict],
    param_sensitivity: dict,
    context_analysis: dict,
    anomalies: list[dict],
    signal_type: str,
) -> str:
    """【V8.5.2升级】Build AI prompt with win rate - P/L ratio trade-off analysis

    展示Top 10配置的权衡关系，让AI选择最优平衡点
    """
    # 【V8.5.2】Format Top 10 configs with trade-off table
    top_10_table = "\n| Rank | Score | Win Rate | P/L Ratio | Avg Win | Avg Loss | Expectancy | Capture | Max DD |\n"
    top_10_table += "|------|-------|----------|-----------|---------|----------|------------|---------|--------|\n"

    for i, config in enumerate(top_10_configs[:10], 1):
        m = config["metrics"]
        win_rate = m.get("win_rate", 0) * 100
        pl_ratio = m.get("profit_loss_ratio", 0)
        avg_win = m.get("avg_win", 0)
        avg_loss = m.get("avg_loss", 0)
        expectancy = m.get("expectancy", 0)
        capture = m.get("capture_rate", 0) * 100
        max_dd = m.get("max_drawdown", 0) * 100

        top_10_table += f"| {i:2d}   | {config['score']:.3f} | {win_rate:5.1f}% | {pl_ratio:5.2f}:1 | {avg_win:+5.2f}% | {avg_loss:5.2f}% | {expectancy:+5.2f}% | {capture:5.1f}% | {max_dd:4.1f}% |\n"

    # Format Top 3 configs (detail view)
    top_3_str = ""
    for i, config in enumerate(top_10_configs[:3], 1):
        top_3_str += f"\nRank {i}:\n"
        top_3_str += f"  Score: {config['score']:.3f}\n"
        m = config["metrics"]
        top_3_str += f"  Win Rate: {m.get('win_rate', 0) * 100:.1f}%\n"
        top_3_str += f"  P/L Ratio: {m.get('profit_loss_ratio', 0):.2f}:1\n"
        top_3_str += f"  Expectancy: {m.get('expectancy', 0):+.2f}%\n"
        top_3_str += f"  Capture Rate: {m.get('capture_rate', 0) * 100:.0f}%\n"
        top_3_str += f"  Avg Profit: {m.get('avg_profit', 0):.1f}%\n"
        # Show key params (including TP/SL)
        params = config["params"]
        top_3_str += f"  Key Params: signal≥{params.get('min_signal_score', 60)}, "
        top_3_str += f"consensus≥{params.get('min_consensus', 3)}, "
        top_3_str += f"RR≥{params.get('min_risk_reward', 2.0):.1f}, "
        top_3_str += f"TP={params.get('atr_tp_multiplier', 4.0):.1f}×ATR, "
        top_3_str += f"SL={params.get('atr_stop_multiplier', 1.5):.1f}×ATR\n"

    # Format parameter sensitivity (Top 3)
    sensitivity_str = ""
    sorted_params = sorted(
        param_sensitivity.items(), key=lambda x: abs(x[1]["avg_impact"]), reverse=True
    )[:3]
    for param_name, sensitivity in sorted_params:
        sensitivity_str += f"\n  • {param_name}: {sensitivity['importance']} importance"
        sensitivity_str += f" (impact={sensitivity['avg_impact']:+.3f})"

    # Format context insights
    insights_str = "\n".join([
        f"  • {insight}" for insight in context_analysis.get("key_insights", [])[:3]
    ])

    # Format anomalies
    anomalies_str = ""
    for anomaly in anomalies[:2]:
        anomalies_str += f"\n  • {anomaly.get('type', 'unknown')}: {anomaly.get('description', 'N/A')}"

    # 【V8.5.2】Construct enhanced prompt with trade-off analysis
    prompt = f"""You are an expert in trading parameter optimization. 

Your task: Analyze the trade-off between win rate, profit/loss ratio, and total profit to find the optimal balance.

Signal Type: {signal_type.upper()}

=== Trade-Off Analysis (Top 10 Configurations) ===
{top_10_table}

**Key Patterns to Identify:**
- High win rate + Low P/L ratio → Early exits (leaving money on table)
- Low win rate + High P/L ratio → Getting stopped out too often
- Balanced configs → Optimal expectancy

=== Detailed View (Top 3) ===
{top_3_str}

=== Parameter Sensitivity ===
{sensitivity_str}

=== Market Context ===
{insights_str}

=== Anomalies ===
{anomalies_str if anomalies_str else "  None"}

=== Your Task ===

1. **Identify the optimal trade-off:**
   - Which rank has the best balance between win rate and P/L ratio?
   - Is expectancy maximized? (Expectancy = Win Rate × Avg Win + Loss Rate × Avg Loss)
   - Are there red flags? (e.g., Win Rate > 60% but P/L < 1.5 = early exits)

2. **Adjust TP/SL if needed:**
   - If P/L ratio < 1.5 → Consider increasing TP multiplier
   - If win rate < 30% → Consider decreasing SL multiplier or increasing TP
   - If max drawdown > 20% → Consider tighter risk controls

3. **Select the best configuration:**
   - Rank 1 may not be optimal if it has extreme trade-offs
   - Consider Rank 2-10 if they have better balance

Please respond in JSON format:

{{
    "needs_adjustment": true/false,
    "selected_rank": 1,  // 1-10
    "param_adjustments": {{
        // Only specify params that need adjustment
        // Available: "atr_tp_multiplier", "atr_stop_multiplier", "min_signal_score", etc.
        // Example: "atr_tp_multiplier": 4.5
    }},
    "reasoning_en": "Why this configuration achieves the best trade-off between win rate, P/L ratio, and expectancy",
    "trade_off_analysis": "Explain the trade-off pattern observed (e.g., 'Rank 1 has high win rate but low P/L ratio due to early exits')",
    "key_insights_en": [
        "Insight about win rate pattern",
        "Insight about P/L ratio optimization"
    ],
    "expected_improvement": {{
        "win_rate": "↑/↓/→",
        "pl_ratio": "↑/↓/→",
        "expectancy": "+X%"
    }}
}}

Respond with ONLY the JSON, no additional text."""

    return prompt


def call_deepseek_for_optimization(prompt: str) -> str | None:
    """Call DeepSeek API for optimization decision

    Uses existing call_deepseek function from main file
    """
    try:
        # 尝试导入主文件的call_deepseek函数
        import os
        import sys

        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

        # 动态导入（避免循环依赖）
        import importlib.util

        spec = importlib.util.spec_from_file_location("main", "qwen_多币种智能版.py")
        if spec and spec.loader:
            main_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(main_module)

            if hasattr(main_module, "call_deepseek"):
                response = main_module.call_deepseek(
                    prompt=prompt, max_tokens=500, temperature=0.3
                )
                return response

        # 如果导入失败，返回None（跳过AI决策）
        return None

    except Exception as e:
        print(f"⚠️  AI API调用失败: {e}")
        return None


def parse_ai_optimization_response(ai_response: str | None) -> dict | None:
    """Parse AI response (JSON format)

    Returns English decision dict
    """
    if not ai_response:
        return None

    try:
        import json
        import re

        # 提取JSON（AI可能会返回额外的文字）
        json_match = re.search(r"\{.*\}", ai_response, re.DOTALL)
        if json_match:
            json_str = json_match.group(0)
            decision = json.loads(json_str)
            return decision
        return None

    except Exception as e:
        print(f"⚠️  AI响应解析失败: {e}")
        return None


def apply_ai_adjustments(base_params: dict, adjustments: dict) -> dict:
    """Apply AI-suggested parameter adjustments

    Args:
        base_params: Base parameter configuration
        adjustments: AI-suggested adjustments (can be partial)

    Returns:
        Adjusted parameters

    """
    adjusted = base_params.copy()

    # 应用AI建议的调整
    for param_name, new_value in adjustments.items():
        if param_name in adjusted:
            adjusted[param_name] = new_value

    return adjusted


def translate_insights_to_chinese(insights_en: list[str]) -> list[str]:
    """Translate English insights to Chinese for user display

    Simple keyword-based translation for common patterns
    """
    insights_zh = []

    for insight in insights_en:
        # 简单的关键词翻译（可以扩展）
        insight_zh = insight

        # 常见模式翻译
        replacements = {
            "bullish ratio": "阳线比例",
            "best performance": "效果最好",
            "average profit": "平均利润",
            "HH-HL structure": "HH-HL结构",
            "LL-LH structure": "LL-LH结构",
            "support/resistance": "支撑/阻力",
            "test": "测试",
            "times": "次",
            "when": "时",
            "Rank 1 is optimal": "Top 1配置最优",
            "No adjustment needed": "无需调整",
            "Micro-adjust": "微调",
            "Market volatility": "市场波动",
            "Risk": "风险",
        }

        for en, zh in replacements.items():
            insight_zh = insight_zh.replace(en, zh)

        insights_zh.append(f"💡 {insight_zh}")

    return insights_zh


# ============================================================
# 主函数
# ============================================================

if __name__ == "__main__":
    print("V8.3.21回测优化模块（含AI迭代）")
    print("使用方法：从主程序导入 optimize_params_v8321_lightweight")
