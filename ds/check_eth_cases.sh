#!/bin/bash

# ETH行情捕获验证脚本（V8.3.20）
# 使用方法：bash check_eth_cases.sh

cd ~/10-23-bot/ds

echo "=== ETH行情捕获验证（V8.3.20）==="
echo ""

# 案例1：11月4日23:30-11月5日5:30（北京）= 15:30-21:30（UTC）下跌
echo "【案例1：ETH 11月4日下跌】"
echo "北京时间：11月4日23:30 - 11月5日5:30"
echo "UTC时间：11月4日15:30 - 11月4日21:30"
echo ""

awk -F',' '
NR==1 {
  for(i=1; i<=NF; i++) {
    if($i=="time") time_col=i
    if($i=="coin") coin_col=i
    if($i=="close") price_col=i
    if($i=="risk_reward") rr_col=i
    if($i=="indicator_consensus") consensus_col=i
    if($i=="volume_surge_score") vol_score_col=i
    if($i=="trend_15m") trend_15m_col=i
    if($i=="trend_1h") trend_1h_col=i
    if($i=="trend_4h") trend_4h_col=i
    if($i=="signal_score") signal_col=i
    if($i=="volume") vol_col=i
  }
}
NR>1 && $coin_col=="ETH" && $time_col == 1530 {
  start_price = $price_col
  printf "  起点（15:30 UTC）：价格=$%.2f\n", $price_col
  printf "    趋势：15m=%s, 1h=%s, 4h=%s\n", $trend_15m_col, $trend_1h_col, $trend_4h_col
  printf "    共振=%d, R:R=%.2f, 成交量=%s, 成交量评分=%d, 信号分=%d\n", $consensus_col, $rr_col, $vol_col, $vol_score_col, $signal_col
  
  if ($rr_col >= 3.5 && $consensus_col >= 3) {
    print "    ✅ 满足捕获条件（R:R≥3.5且共振≥3）"
  } else if ($rr_col < 3.5) {
    printf "    ❌ R:R不足（%.2f < 3.5）\n", $rr_col
  } else {
    printf "    ❌ 共振不足（%d < 3）\n", $consensus_col
  }
}
NR>1 && $coin_col=="ETH" && $time_col == 2130 {
  end_price = $price_col
  printf "  终点（21:30 UTC）：价格=$%.2f\n", $price_col
  if (start_price > 0) {
    change_pct = (end_price - start_price) / start_price * 100
    printf "  实际涨跌：%.2f%%\n", change_pct
  }
}
' trading_data/deepseek/market_snapshots/20251104.csv

echo ""
echo "【案例2：ETH 11月9日上涨】"
echo "北京时间：11月9日18:30 - 11月10日9:00"
echo "UTC时间：11月9日10:30 - 11月10日01:00"
echo ""

awk -F',' '
NR==1 {
  for(i=1; i<=NF; i++) {
    if($i=="time") time_col=i
    if($i=="coin") coin_col=i
    if($i=="close") price_col=i
    if($i=="risk_reward") rr_col=i
    if($i=="indicator_consensus") consensus_col=i
    if($i=="volume_surge_score") vol_score_col=i
    if($i=="trend_15m") trend_15m_col=i
    if($i=="signal_score") signal_col=i
  }
}
NR>1 && $coin_col=="ETH" && $time_col == 1030 {
  start_price = $price_col
  printf "  起点（10:30 UTC）：价格=$%.2f, 趋势(15m)=%s\n", $price_col, $trend_15m_col
  printf "    共振=%d, R:R=%.2f, 成交量评分=%d, 信号分=%d\n", $consensus_col, $rr_col, $vol_score_col, $signal_col
  
  if ($rr_col >= 3.5 && $consensus_col >= 3) {
    print "    ✅ 满足捕获条件"
  } else if ($rr_col < 3.5) {
    printf "    ❌ R:R不足（%.2f < 3.5）\n", $rr_col
  } else {
    printf "    ❌ 共振不足（%d < 3）\n", $consensus_col
  }
}
' trading_data/deepseek/market_snapshots/20251109.csv

awk -F',' '
NR==1 {
  for(i=1; i<=NF; i++) {
    if($i=="time") time_col=i
    if($i=="coin") coin_col=i
    if($i=="close") price_col=i
  }
}
NR>1 && $coin_col=="ETH" && $time_col == 100 {
  printf "  终点（01:00 UTC次日）：价格=$%.2f\n", $price_col
}
' trading_data/deepseek/market_snapshots/20251110.csv

echo ""
echo "【案例3：ETH 11月5日上涨】"
echo "北京时间：11月5日5:45 - 11月6日4:15"
echo "UTC时间：11月4日21:45 - 11月5日20:15"
echo ""

awk -F',' '
NR==1 {
  for(i=1; i<=NF; i++) {
    if($i=="time") time_col=i
    if($i=="coin") coin_col=i
    if($i=="close") price_col=i
    if($i=="risk_reward") rr_col=i
    if($i=="indicator_consensus") consensus_col=i
    if($i=="volume_surge_score") vol_score_col=i
    if($i=="trend_15m") trend_15m_col=i
    if($i=="signal_score") signal_col=i
  }
}
NR>1 && $coin_col=="ETH" && $time_col == 2145 {
  printf "  起点（21:45 UTC）：价格=$%.2f, 趋势(15m)=%s\n", $price_col, $trend_15m_col
  printf "    共振=%d, R:R=%.2f, 成交量评分=%d, 信号分=%d\n", $consensus_col, $rr_col, $vol_score_col, $signal_col
  
  if ($rr_col >= 3.5 && $consensus_col >= 3) {
    print "    ✅ 满足捕获条件"
  } else if ($rr_col < 3.5) {
    printf "    ❌ R:R不足（%.2f < 3.5）\n", $rr_col
  } else {
    printf "    ❌ 共振不足（%d < 3）\n", $consensus_col
  }
}
' trading_data/deepseek/market_snapshots/20251104.csv

echo ""
echo "【案例4：ETH 11月4日下跌（延长版）】"
echo "北京时间：11月4日23:30 - 11月5日5:45"
echo "UTC时间：11月4日15:30 - 11月4日21:45"
echo "（与案例1起点相同，终点延长15分钟，终点即案例3起点）"

echo ""
echo "=== 总结 ==="
echo "捕获条件：R:R≥3.5 且 共振≥3 且 信号分≥75"

