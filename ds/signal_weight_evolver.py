"""
信号权重遗传算法进化器 V8.7.3
基于交易员建议实现 - 从确定性陷阱到期望型评分

核心理念：
1. 适应度函数 = 高分必须对应高利润
2. 通过进化算法自动发现最适合当前市场状态的权重组合
3. 突破人工定义权重的局限性

@author: 交易员建议 + AI实现
@date: 2025-11-23
"""

import random
import numpy as np
import copy
from typing import List, Dict, Any


class SignalWeightEvolver:
    """信号权重遗传算法进化器"""
    
    def __init__(self, opportunities: List[Dict], signal_type: str = 'swing'):
        """
        初始化进化器
        
        Args:
            opportunities: Phase 1识别出的客观机会列表 (必须包含snapshot数据)
            signal_type: 'scalping' 或 'swing'
        """
        self.opportunities = opportunities
        self.signal_type = signal_type
        
        # 定义基因组（需要优化的维度）- V8.7.3新维度
        if signal_type == 'scalping':
            self.genes = [
                'momentum', 'volume', 'breakout', 'pattern', 'trend_align',
                'volatility', 'volume_pulse', 'momentum_accel',
                'space_factor', 'position_factor'  # V8.7.3新维度
            ]
        else:
            self.genes = [
                'momentum', 'volume', 'breakout', 'trend_align', 
                'ema_divergence', 'trend_4h_strength',
                'space_factor', 'position_factor', 'freshness_factor'  # V8.7.3新维度
            ]
    
    def _extract_raw_components(self, snapshot: Dict) -> Dict[str, float]:
        """
        从快照中提取各维度的原始强度（归一化到0-1.5之间）
        
        这部分逻辑从calculate_signal_score_components抽象出来
        """
        comps = {}
        
        # 1. 动量强度
        close = float(snapshot.get('close', 1))
        open_p = float(snapshot.get('open', 1))
        if open_p > 0:
            mom = abs((close - open_p) / open_p)
            comps['momentum'] = min(1.5, mom * 100)  # 0.5%->0.5, 1.5%->1.5
        else:
            comps['momentum'] = 0
        
        # 2. 成交量
        vol_ratio = float(snapshot.get('volume_ratio', 0))
        comps['volume'] = max(0, min(1.5, vol_ratio - 1.0))  # 1.0x->0, 2.0x->1.0
        
        # 3. 趋势对齐
        trend_4h = str(snapshot.get('trend_4h', ''))
        trend_1h = str(snapshot.get('trend_1h', ''))
        trend_15m = str(snapshot.get('trend_15m', ''))
        direction = '多' if snapshot.get('side') == 'long' else '空'
        
        align_count = 0
        if direction in trend_4h:
            align_count += 1
        if direction in trend_1h:
            align_count += 1
        if direction in trend_15m:
            align_count += 1
        comps['trend_align'] = align_count / 3.0  # 0, 0.33, 0.67, 1.0
        
        # 4. 突破
        breakout_str = str(snapshot.get('breakout', ''))
        if '强势' in breakout_str:
            comps['breakout'] = 1.5
        elif '突破' in breakout_str:
            comps['breakout'] = 1.0
        elif '震荡' in breakout_str:
            comps['breakout'] = 0.3
        else:
            comps['breakout'] = 0
        
        # 5. 形态
        pattern_str = str(snapshot.get('pattern', ''))
        if '强' in pattern_str or '持续' in pattern_str:
            comps['pattern'] = 1.0
        elif '反转' in pattern_str:
            comps['pattern'] = 0.8
        else:
            comps['pattern'] = 0.3
        
        # 6. 波动率 (超短线专属)
        if self.signal_type == 'scalping':
            volatility_ratio = float(snapshot.get('volatility_ratio', 0))
            comps['volatility'] = max(0, min(1.5, volatility_ratio - 1.0))
            
            # 7. 成交量脉冲
            volume_surge = float(snapshot.get('volume_surge', 0))
            comps['volume_pulse'] = min(1.0, volume_surge / 2.0)  # 2x->1.0
            
            # 8. 动量加速
            momentum_accel = float(snapshot.get('momentum_acceleration', 0))
            comps['momentum_accel'] = min(1.0, abs(momentum_accel) * 10)  # 0.1->1.0
        
        # 9. EMA发散 (波段专属)
        if self.signal_type == 'swing':
            ema_div = float(snapshot.get('ema_divergence', 0))
            comps['ema_divergence'] = min(1.0, abs(ema_div) / 5.0)  # 5%->1.0
            
            # 10. 4H趋势强度
            trend_4h_strength = float(snapshot.get('trend_4h_strength', 0))
            comps['trend_4h_strength'] = min(1.0, trend_4h_strength / 80)  # 80分->1.0
        
        # 🆕 V8.7.3新维度
        # 11. 空间因子
        atr = float(snapshot.get('atr_14', 1))
        if direction == '多':
            nearest_resistance = float(snapshot.get('nearest_resistance', float('inf')))
            if nearest_resistance < float('inf') and atr > 0:
                space_atr_multiple = (nearest_resistance - close) / atr
                if space_atr_multiple > 5:
                    comps['space_factor'] = 1.5  # 优秀空间
                elif space_atr_multiple > 3:
                    comps['space_factor'] = 1.0  # 良好空间
                elif space_atr_multiple > 2:
                    comps['space_factor'] = 0.5  # 一般空间
                else:
                    comps['space_factor'] = 0  # 空间不足
            else:
                comps['space_factor'] = 1.2  # 无明显阻力
        else:  # 空方向
            nearest_support = float(snapshot.get('nearest_support', 0))
            if nearest_support > 0 and atr > 0:
                space_atr_multiple = (close - nearest_support) / atr
                if space_atr_multiple > 5:
                    comps['space_factor'] = 1.5
                elif space_atr_multiple > 3:
                    comps['space_factor'] = 1.0
                elif space_atr_multiple > 2:
                    comps['space_factor'] = 0.5
                else:
                    comps['space_factor'] = 0
            else:
                comps['space_factor'] = 1.2  # 无明显支撑
        
        # 12. 位置因子
        position_status = str(snapshot.get('position_status', ''))
        if direction == '多':
            if 'at_support' in position_status.lower():
                comps['position_factor'] = 1.5  # 极佳位置
            elif 'at_resistance' in position_status.lower():
                comps['position_factor'] = 0  # 糟糕位置
            else:
                comps['position_factor'] = 0.5  # 中性位置
        else:  # 空方向
            if 'at_resistance' in position_status.lower():
                comps['position_factor'] = 1.5
            elif 'at_support' in position_status.lower():
                comps['position_factor'] = 0
            else:
                comps['position_factor'] = 0.5
        
        # 13. 新鲜度因子 (波段专属)
        if self.signal_type == 'swing':
            trend_age = float(snapshot.get('mkt_struct_age_candles', 0))
            if trend_age < 20:
                comps['freshness_factor'] = 1.5  # 新鲜趋势
            elif trend_age < 40:
                comps['freshness_factor'] = 1.0  # 年轻趋势
            elif trend_age < 60:
                comps['freshness_factor'] = 0.5  # 成熟趋势
            else:
                comps['freshness_factor'] = 0  # 老化趋势
        
        return comps
    
    def _calculate_score_batch(self, weights: Dict[str, float]) -> tuple:
        """
        使用给定的权重，批量计算所有机会的得分
        
        Returns:
            (scores, profits): 得分列表和利润列表
        """
        scores = []
        profits = []
        
        for opp in self.opportunities:
            snapshot = opp.get('snapshot', {})
            if not snapshot:
                continue
                
            raw_components = self._extract_raw_components(snapshot)
            
            # 计算总分
            score = 50  # 基础分
            for gene in self.genes:
                strength = raw_components.get(gene, 0)
                weight = weights.get(gene, 0)
                score += strength * weight
            
            scores.append(score)
            profits.append(opp.get('objective_profit', 0))
        
        return scores, profits
    
    def fitness_function(self, weights: Dict[str, float]) -> float:
        """
        适应度函数：评估这组权重的质量
        
        核心思想：高分必须对应高利润
        
        评估维度：
        1. 头部效应 (60%)：分数最高的20%机会的平均利润
        2. 相关性 (30%)：分数与利润的皮尔逊相关系数
        3. 区分度 (10%)：分数的标准差（避免所有机会都80分）
        """
        scores, profits = self._calculate_score_batch(weights)
        
        if not scores or len(scores) < 5:
            return 0
        
        # 1. 相关性得分 (Pearson Correlation)
        # 我们希望分数和利润正相关
        try:
            if np.std(scores) > 0:
                correlation = np.corrcoef(scores, profits)[0, 1]
            else:
                correlation = 0
            if np.isnan(correlation):
                correlation = 0
        except Exception:
            correlation = 0
        
        # 2. 头部效应 (Top Tier Profit)
        # 找出分数最高的20%的机会，看它们的平均利润
        paired = list(zip(scores, profits))
        paired.sort(key=lambda x: x[0], reverse=True)
        top_20_count = max(1, int(len(paired) * 0.2))
        top_20_profit = np.mean([p for s, p in paired[:top_20_count]])
        
        # 3. 区分度 (Standard Deviation)
        # 我们不希望所有机会都是80分，要有区分度
        score_std = np.std(scores)
        
        # 综合评分公式
        # 权重：头部利润(60%) + 相关性(30%) + 区分度(10%)
        fitness = (top_20_profit * 2.0) + (correlation * 20) + (score_std * 0.5)
        
        return fitness
    
    def evolve(
        self, generations: int = 10, population_size: int = 20
    ) -> Dict[str, Any]:
        """
        运行进化算法
        
        Args:
            generations: 进化代数
            population_size: 种群大小
            
        Returns:
            最优权重组合
        """
        # 1. 初始化种群 (随机生成权重)
        population = []
        for _ in range(population_size):
            # 随机生成权重，每个基因5-40之间
            genome = {gene: random.randint(5, 40) for gene in self.genes}
            population.append(genome)
        
        best_genome = None
        best_fitness = -float('inf')
        
        print(f"\n🧬 启动信号权重进化 ({generations}代, 种群{population_size})...")
        
        for gen in range(generations):
            # 评估
            ranked_population = []
            for genome in population:
                fit = self.fitness_function(genome)
                ranked_population.append((fit, genome))
            
            # 排序
            ranked_population.sort(key=lambda x: x[0], reverse=True)
            
            current_best_fit = ranked_population[0][0]
            current_best_genome = ranked_population[0][1]
            
            if current_best_fit > best_fitness:
                best_fitness = current_best_fit
                best_genome = copy.deepcopy(current_best_genome)
                fitness_msg = f"   Generation {gen+1}: 🆕 New Best Fitness "
                print(f"{fitness_msg}{best_fitness:.2f}")
                # 显示当前最优权重
                sorted_genes = sorted(
                    best_genome.items(), key=lambda x: x[1], reverse=True
                )
                top3_genes = sorted_genes[:3]
                weights_str = ', '.join([f'{k}={v}' for k, v in top3_genes])
                print(f"      Top3权重: {weights_str}")
            
            # 优胜劣汰：保留前20%
            survivors = [g for f, g in ranked_population[:int(population_size * 0.2)]]
            
            # 繁殖与变异
            new_population = survivors[:]  # 精英保留
            while len(new_population) < population_size:
                # 随机选择一个幸存者作为父代
                parent = random.choice(survivors)
                child = parent.copy()
                
                # 变异：随机调整1-3个基因的权重
                for _ in range(random.randint(1, 3)):
                    gene_to_mutate = random.choice(self.genes)
                    mutation = random.randint(-5, 5)
                    mutated_value = child[gene_to_mutate] + mutation
                    child[gene_to_mutate] = max(0, min(50, mutated_value))
                
                new_population.append(child)
            
            population = new_population
        
        print(f"\n✅ 进化完成！最优适应度: {best_fitness:.2f}")
        print("   最优权重组合:")
        for gene in sorted(best_genome.keys()):
            print(f"      {gene}: {best_genome[gene]}")
        
        # 添加name字段
        best_genome['name'] = 'AI_Evolved'
        
        return best_genome


def integrate_evolver_to_phase2(
    confirmed_opportunities: Dict,
    scalping_weight_candidates: List[Dict],
    swing_weight_candidates: List[Dict],
    quick_evolve: bool = True
) -> tuple:
    """
    将进化器集成到Phase 2流程中
    
    Args:
        confirmed_opportunities: Phase 1识别出的机会
        scalping_weight_candidates: 超短线权重候选列表
        swing_weight_candidates: 波段权重候选列表
        quick_evolve: 是否使用快速模式（5代，适合在线优化）
        
    Returns:
        (updated_scalping_candidates, updated_swing_candidates)
    """
    generations = 5 if quick_evolve else 10
    population_size = 20
    
    # 超短线进化
    if confirmed_opportunities and 'scalping' in confirmed_opportunities:
        train_opps = confirmed_opportunities['scalping']['opportunities']
        
        if len(train_opps) >= 20:  # 至少需要20个样本
            print("\n  🧬 【Phase 1.5】超短线信号权重自由进化")
            print("     目标: 寻找与【大幅盈利】强相关的权重组合...")
            
            evolver = SignalWeightEvolver(train_opps, signal_type='scalping')
            best_scalping_weights = evolver.evolve(
                generations=generations, population_size=population_size
            )
            
            scalping_weight_candidates.append(best_scalping_weights)
            count = len(scalping_weight_candidates)
            print(f"     ✅ AI_Evolved权重已加入候选池 (共{count}组)")
        else:
            print(f"\n  ⚠️ 超短线样本不足({len(train_opps)}<20)，跳过进化")
    
    # 波段进化
    if confirmed_opportunities and 'swing' in confirmed_opportunities:
        train_opps = confirmed_opportunities['swing']['opportunities']
        
        if len(train_opps) >= 20:
            print("\n  🧬 【Phase 1.5】波段信号权重自由进化")
            print("     目标: 寻找与【大幅盈利】强相关的权重组合...")
            
            evolver = SignalWeightEvolver(train_opps, signal_type='swing')
            best_swing_weights = evolver.evolve(
                generations=generations, population_size=population_size
            )
            
            swing_weight_candidates.append(best_swing_weights)
            count = len(swing_weight_candidates)
            print(f"     ✅ AI_Evolved权重已加入候选池 (共{count}组)")
        else:
            print(f"\n  ⚠️ 波段样本不足({len(train_opps)}<20)，跳过进化")
    
    return scalping_weight_candidates, swing_weight_candidates

