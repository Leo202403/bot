from flask import Flask, jsonify, request
import requests
import logging
from datetime import datetime
import pytz
import json
import os
import random
# from PIL import Image  # 临时注释，架构不匹配
from io import BytesIO, StringIO
# import numpy as np  # 临时注释
import base64
import traceback
import re
from datetime import datetime, timedelta
import csv
import time  # 【V8.5.2.4.88优化】添加时间模块用于缓存


app = Flask(__name__)

# 【V8.5.2.4.88优化】数据缓存配置
# 缓存summary数据，减少频繁读取CSV文件的内存和CPU开销
SUMMARY_CACHE = {}
CACHE_DURATION = 30  # 缓存有效期（秒）

# ==================== 时区转换辅助函数 ====================

def utc_to_beijing_time(utc_time_str):
    """
    将UTC时间字符串转换为北京时间字符串
    服务器在美国，存储的是UTC时间，需要+8小时展示给用户
    
    :param utc_time_str: UTC时间字符串，如 "2025-10-29 06:00:00"
    :return: 北京时间字符串，如 "2025-10-29 14:00:00"
    """
    if not utc_time_str or not utc_time_str.strip():
        return utc_time_str
    
    try:
        # 支持多种时间格式
        for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%m-%d %H:%M', '%Y-%m-%d']:
            try:
                utc_dt = datetime.strptime(utc_time_str.strip(), fmt)
                # 添加8小时转换为北京时间
                beijing_dt = utc_dt + timedelta(hours=8)
                # 保持原格式返回
                return beijing_dt.strftime(fmt)
            except ValueError:
                continue
        
        # 如果都不匹配，返回原字符串
        return utc_time_str
    except Exception as e:
        logging.error(f"时间转换失败: {utc_time_str}, 错误: {e}")
        return utc_time_str

def beijing_to_utc_time(beijing_time_str):
    """
    将北京时间字符串转换为UTC时间字符串
    用户输入的是北京时间，需要-8小时去查询UTC数据
    
    :param beijing_time_str: 北京时间字符串
    :return: UTC时间字符串
    """
    if not beijing_time_str or not beijing_time_str.strip():
        return beijing_time_str
    
    try:
        for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d']:
            try:
                beijing_dt = datetime.strptime(beijing_time_str.strip(), fmt)
                # 减8小时转换为UTC
                utc_dt = beijing_dt - timedelta(hours=8)
                return utc_dt.strftime(fmt)
            except ValueError:
                continue
        
        return beijing_time_str
    except Exception as e:
        logging.error(f"时间转换失败: {beijing_time_str}, 错误: {e}")
        return beijing_time_str

# ==================== 交易指标计算辅助函数 ====================

def calculate_max_drawdown(trades_history):
    """
    计算最大回撤
    :param trades_history: 交易历史列表（已平仓的交易）
    :return: 最大回撤百分比
    """
    if not trades_history:
        return 0.0
    
    # 初始资金（根据模型数量判断）
    initial_capital = 100.0
    
    # 按时间排序
    sorted_trades = sorted(trades_history, key=lambda x: x.get('开仓时间', ''))
    
    # 计算每笔交易后的资产曲线
    capital = initial_capital
    peak = capital
    max_dd = 0.0
    
    for trade in sorted_trades:
        if trade.get('平仓时间'):  # 只计算已平仓的交易
            pnl = float(trade.get('盈亏(U)', 0) or 0)
            capital += pnl
            
            # 更新峰值
            if capital > peak:
                peak = capital
            
            # 计算当前回撤
            if peak > 0:
                drawdown = (peak - capital) / peak * 100
                if drawdown > max_dd:
                    max_dd = drawdown
    
    return max_dd

def calculate_sharpe_ratio(trades_history, pnl_history=None, initial_capital=100.0):
    """
    计算夏普比率（年化）
    :param trades_history: 交易历史列表
    :param pnl_history: 盈亏历史数据（CSV格式，包含总资产字段）
    :param initial_capital: 初始资金
    :return: 夏普比率
    """
    if not trades_history or len(trades_history) < 2:
        return 0.0
    
    # 如果有pnl_history，使用更精确的计算方式
    if pnl_history and len(pnl_history) > 1:
        try:
            # 提取资产序列
            assets = []
            for record in pnl_history:
                asset_value = float(record.get('总资产', record.get('total_assets', 0)) or 0)
                if asset_value > 0:
                    assets.append(asset_value)
            
            if len(assets) < 2:
                return 0.0
            
            # 计算收益率序列
            returns = []
            for i in range(1, len(assets)):
                if assets[i-1] > 0:
                    ret = (assets[i] - assets[i-1]) / assets[i-1]
                    returns.append(ret)
            
            if not returns:
                return 0.0
            
            # 计算收益率的均值和标准差
            mean_return = sum(returns) / len(returns)
            variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
            std_return = variance ** 0.5
            
            if std_return == 0:
                return 0.0
            
            # 假设无风险利率为0（或年化2%）
            risk_free_rate = 0.00  # 每个周期的无风险收益率
            
            # 计算夏普比率
            sharpe = (mean_return - risk_free_rate) / std_return
            
            # 年化夏普比率（假设每15分钟一个数据点，一年约35040个点）
            # 但通常使用sqrt(交易周期数/年)来年化
            # 这里简化处理：sqrt(365*24*4) = sqrt(35040) ≈ 187
            annualization_factor = (365 * 24 * 4) ** 0.5
            annual_sharpe = sharpe * annualization_factor
            
            return annual_sharpe
        except Exception as e:
            logging.error(f"使用盈亏历史计算夏普比率失败: {e}")
    
    # 备用方案：使用交易记录计算
    try:
        # 按时间排序
        sorted_trades = sorted([t for t in trades_history if t.get('平仓时间')], 
            key=lambda x: x.get('平仓时间', ''))
        
        if len(sorted_trades) < 2:
            return 0.0
        
        # 计算每笔交易的收益率
        capital = initial_capital
        returns = []
        
        for trade in sorted_trades:
            pnl = float(trade.get('盈亏(U)', 0) or 0)
            if capital > 0:
                ret = pnl / capital
                returns.append(ret)
                capital += pnl
        
        if not returns:
            return 0.0
        
        # 计算均值和标准差
        mean_return = sum(returns) / len(returns)
        variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
        std_return = variance ** 0.5
        
        if std_return == 0:
            return 0.0
        
        # 计算交易频率（每年交易次数）
        start_time = datetime.strptime(sorted_trades[0].get('开仓时间', ''), '%Y-%m-%d %H:%M:%S')
        end_time = datetime.strptime(sorted_trades[-1].get('平仓时间', ''), '%Y-%m-%d %H:%M:%S')
        days_elapsed = (end_time - start_time).total_seconds() / 86400
        
        if days_elapsed <= 0:
            return 0.0
        
        trades_per_year = len(sorted_trades) * (365 / days_elapsed)
        
        # 年化夏普比率
        sharpe = mean_return / std_return
        annual_sharpe = sharpe * (trades_per_year ** 0.5)
        
        return annual_sharpe
    except Exception as e:
        logging.error(f"计算夏普比率失败: {e}")
        return 0.0

def filter_data_by_time_range(data_list, time_field, range_type='all', start_date='', end_date=''):
    """
    根据时间范围过滤数据
    :param data_list: 数据列表
    :param time_field: 时间字段名
    :param range_type: 范围类型（all/day/week/month/custom）
    :param start_date: 自定义开始日期
    :param end_date: 自定义结束日期
    :return: 过滤后的数据列表
    """
    if range_type == 'all':
        return data_list
    
    from datetime import timezone
    beijing_tz = timezone(timedelta(hours=8))
    now_beijing = datetime.now(beijing_tz).replace(tzinfo=None)
    
    # 计算时间范围的起始时间（北京时间）
    if range_type == 'day':
        start_time = now_beijing.replace(hour=0, minute=0, second=0, microsecond=0)
        end_time = None
    elif range_type == 'week':
        days_since_monday = now_beijing.weekday()
        start_time = (now_beijing - timedelta(days=days_since_monday)).replace(hour=0, minute=0, second=0, microsecond=0)
        end_time = None
    elif range_type == 'month':
        start_time = now_beijing.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end_time = None
    elif range_type == 'custom' and start_date and end_date:
        start_time = datetime.strptime(start_date, '%Y-%m-%d')
        end_time = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
    else:
        return data_list
    
    # 🔥 时区转换：服务器在美国，CSV存储的是UTC时间
    # 用户选择的是北京时间，需要转换为UTC去查询数据
    # 北京时间 = UTC + 8小时，所以 UTC = 北京时间 - 8小时
    start_time = start_time - timedelta(hours=8)
    if end_time:
        end_time = end_time - timedelta(hours=8)
    
    # 过滤数据
    filtered = []
    parse_errors = 0
    
    for item in data_list:
        time_str = item.get(time_field, '')
        if not time_str:
            continue
        
        item_time = None
        
        # 尝试多种时间格式
        time_formats = [
            '%Y-%m-%d %H:%M:%S',  # 2025-10-28 12:11:00
            '%m-%d %H:%M',        # 10-28 12:11
            '%Y-%m-%d %H:%M',     # 2025-10-28 12:11
            '%Y-%m-%d',           # 2025-10-28
        ]
        
        for fmt in time_formats:
            try:
                item_time = datetime.strptime(time_str.strip(), fmt)
                # 如果格式是 MM-DD，需要补充年份
                if fmt == '%m-%d %H:%M':
                    item_time = item_time.replace(year=now_beijing.year)
                break
            except:
                continue
        
        # 如果还是解析失败，尝试去掉毫秒
        if item_time is None:
            try:
                item_time = datetime.strptime(time_str.split('.')[0].strip(), '%Y-%m-%d %H:%M:%S')
            except:
                parse_errors += 1
                continue
        
        # 应用时间过滤
        if end_time:
            if start_time <= item_time < end_time:
                filtered.append(item)
        else:
            if item_time >= start_time:
                filtered.append(item)
    
    if parse_errors > 0:
        logging.warning(f"[filter_data_by_time_range] 时间过滤中有 {parse_errors} 条记录时间格式解析失败")
    
    logging.info(f"[filter_data_by_time_range] 字段={time_field}, 范围={range_type}, 输入={len(data_list)}, 输出={len(filtered)}")
    
    return filtered

# 设置日志格式，日志级别设为DEBUG以便于调试
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# API 信息
pixabay_api_key = "46715692-0f29fcea05d287ecaded6b2b0"
wanwei_api_url = "https://route.showapi.com/856-2"
wanwei_api_key = "6682347756324c57aef9e8380EA03bA6"

# 缓存文件路径
cache_file_path = "daily_color_cache.json"

# 五行和颜色映射规则
dizhi_wuxing_mapping = { 
    '亥': '水', '子': '水', '寅': '木', '卯': '木',
    '巳': '火', '午': '火', '申': '金', '酉': '金',
    '辰': '土', '戌': '土', '丑': '土', '未': '土'
}

wuxing_color_mapping = {'金': 'white', '木': 'green', '水': 'black', '火': 'red', '土': 'yellow'}
wuxing_relationship = {
    '金': '水',  # 金生水
    '木': '火',  # 木生火
    '水': '木',  # 水生木
    '火': '土',  # 火生土
    '土': '金'   # 土生金
}

color_keywords_mapping = {
    'white': ['white objects', 'white wallpaper', 'white dove', 'white building', 'white furniture'],
    'green': ['green nature', 'green forest', 'green plant', 'green wallpaper', 'green leaf'],
    'black': ['black car', 'black sky', 'black wallpaper', 'black architecture', 'black bird'],
    'red': ['red flowers', 'red wallpaper', 'red sunset', 'red car', 'red building'],
    'yellow': ['yellow flowers', 'yellow wallpaper', 'yellow sunset', 'yellow fruit', 'yellow car']
}

# 获取当前北京时间
def get_beijing_time():
    tz = pytz.timezone('Asia/Shanghai')
    now = datetime.now(tz)
    logging.debug("获取当前北京时间成功")
    return now.strftime('%Y%m%d')

# 缓存操作函数：保存日期和颜色
def save_cache(date, color):
    cache_data = {'date': date, 'color': color}
    with open(cache_file_path, 'w') as cache_file:
        json.dump(cache_data, cache_file)
    logging.info(f"缓存保存成功：{cache_data}")

# 缓存加载函数
def load_cache():
    if os.path.exists(cache_file_path):
        with open(cache_file_path, 'r') as cache_file:
            cache_data = json.load(cache_file)
            logging.info(f"从缓存加载数据：{cache_data}")
            return cache_data
    logging.info("无缓存数据，首次运行")
    return None

# 从万维易流 API 获取当天地支信息
def get_ganzhi_from_api():
    ymd = get_beijing_time()
    params = {
        'appKey': wanwei_api_key,
        'ymd': ymd
    }
    response = requests.get(wanwei_api_url, params=params)
    logging.info(f"调用万维易流API，URL: {wanwei_api_url}, 参数: {params}")
    if response.status_code == 200:
        data = response.json()
        logging.info(f"万维易流API响应数据: {data}")
        if 'showapi_res_body' in data and 'ganzhi' in data['showapi_res_body']:
            ganzhi = data['showapi_res_body']['ganzhi']
            # 分割干支字符串，提取年、月、日干支
            ganzhi_parts = ganzhi.split()
            if len(ganzhi_parts) == 3:
                # 返回日干支的地支部分
                dizhi = ganzhi_parts[2][-2] if len(ganzhi_parts[2]) > 1 else ganzhi_parts[2]
                logging.debug(f"获取到的日干支地支部分为: {dizhi}")
                return dizhi
    logging.error("无法从API获取干支信息或响应数据缺少'ganzhi'")
    return None

# 获取当天五行颜色
def get_wuxing_color(specified_date):
    logging.debug("进入 get_wuxing_color 函数")
    cache_data = load_cache()
    if cache_data and cache_data['date'] == specified_date:
        logging.info(f"缓存日期与当前日期匹配，使用缓存的颜色数据：{cache_data['color']}")
        return cache_data['color']
    
    logging.info("缓存日期与当前日期不匹配或无缓存，将调用API重新获取干支信息")
    ganzhi = get_ganzhi_from_api()
    if ganzhi:
        color = calculate_optimal_color(ganzhi)
        save_cache(specified_date, color)
        return color
    else:
        logging.error("无法推算出颜色，返回默认颜色 'white'")
        return 'white'

# 根据地支确定五行并推荐颜色
def calculate_optimal_color(ganzhi):
    dizhi = ganzhi[-1]  # 只提取地支
    wuxing = dizhi_wuxing_mapping.get(dizhi, '水')  # 根据地支找到五行，默认使用"水"而不是"金"
    
    # 天干和地支结合考虑，若天干为甲乙（木），地支为水时优先推荐木的颜色
    tiangan = ganzhi[0]
    if tiangan in ['甲', '乙'] and wuxing == '水':
        optimal_wuxing = '木'
    else:
        optimal_wuxing = wuxing_relationship.get(wuxing, wuxing)  # 使用相生关系确定最佳五行
    
    color = wuxing_color_mapping.get(optimal_wuxing, 'white')  # 获取最佳五行对应的颜色
    logging.info(f"日柱天干地支为 {tiangan}{dizhi}，地支对应五行为 {wuxing}，相生最佳五行为 {optimal_wuxing}，推荐颜色为 {color}")
    return color

# 从Pixabay获取图片URL
def get_image_url_from_pixabay(color, device_type):
    color_keywords = color_keywords_mapping.get(color, [color])
    search_keyword = random.choice(color_keywords)
    
    url = "https://pixabay.com/api/"
    if device_type == "phone":
        min_width, min_height, orientation = 1170, 2532, 'vertical'
    elif device_type == "desktop":
        min_width, min_height, orientation = 2560, 1600, 'horizontal'
    else:
        min_width, min_height, orientation = 1920, 1080, 'horizontal'
    
    params = {
        'key': pixabay_api_key,
        'q': search_keyword,
        'image_type': 'photo',
        'safesearch': 'true',
        'per_page': 5,
        'min_width': min_width,
        'min_height': min_height,
        'orientation': orientation
    }
    
    response = requests.get(url, params=params)
    logging.info(f"Pixabay API 请求 URL: {response.url}, 状态码: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        logging.info(f"Pixabay API 返回数据: {data}")
        if 'hits' in data and data['hits']:
            selected_image = random.choice(data['hits'])
            image_url = selected_image.get('largeImageURL') or selected_image.get('fullHDURL')
            logging.info(f"获取的图片URL为: {image_url}")
            return image_url
    logging.error("无法从Pixabay获取符合要求的图片")
    return None

# Flask 路由
@app.route('/get-wallpaper', methods=['GET'])
def get_wallpaper():
    date = get_beijing_time()
    logging.info(f"获取当前北京时间，日期: {date}")
    
    color = get_wuxing_color(date)
    if color:
        phone_image_url = get_image_url_from_pixabay(color, device_type="phone")
        desktop_image_url = get_image_url_from_pixabay(color, device_type="desktop")
        
        if phone_image_url and desktop_image_url:
            logging.info(f"返回的手机壁纸URL: {phone_image_url}")
            logging.info(f"返回的电脑壁纸URL: {desktop_image_url}")
            return jsonify({
                'phone_image_url': phone_image_url,
                'desktop_image_url': desktop_image_url
            })
        else:
            logging.error("无法获取图片")
            return jsonify({'error': '无法获取图片'}), 500
    else:
        logging.error("无法推算出颜色")
        return jsonify({'error': '无法推算出颜色'}), 500
    


# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

# 存储会员信息的 CSV 文件路径
DATA_FILE = 'membership_data.csv'

# 初始化 CSV 文件
if not os.path.exists(DATA_FILE):
    with open(DATA_FILE, mode='w', newline='') as file:
        writer = csv.writer(file)
        # 新增列：养号关键词 和 养号总次数
        writer.writerow(['会员ID', '有效期至', '下载次数', '图文下载关键词', '图文下载总次数', '搜索数据关键词', '搜索数据总下载次数', '养号关键词', '养号总次数'])

# 全局数据字典，用于存储会员信息和关键词记录
membership_data = {}
keywords_data = {}          # 图文下载关键词记录
data_keywords_data = {}      # 搜索数据关键词记录
养号_keywords_data = {}       # 养号关键词记录
total_downloads = 0         # 图文下载总次数
data_total_downloads = 0    # 搜索数据总下载次数
养号_total_downloads = 0     # 养号总次数

def generate_养号_params(search_key):
    return {
        "code": 0,
        "msg": "成功",
        "data": {
            "code": None,
            "searchKey": search_key,
            "titleKey": "",
            "enterKey": generate_random_key("01234"),
            "zanKey": generate_random_key("01"),
            "collectKey": generate_random_key("0"),
            "followKey": generate_random_key("012"),
            "commentRead": generate_random_key("01234")
        },
        "msgEn": "success"
    }


# 随机生成 Key 参数
def generate_random_key(base, length=None):
    """
    生成包含 base 字符的随机组合，确保字符均匀分布且不重复。
    
    :param base: 字符的基础字符串，例如 "01234"
    :param length: 生成的 Key 长度，默认为 None，自动选择
    :return: 随机生成的字符串组合
    """
    if length is None:
        length = random.randint(1, len(base))  # 默认生成长度在 1 到 base 长度之间

    # 使用 sample 确保字符不重复且均匀选择
    return ''.join(random.sample(base, length))

# 示例调用
enter_key = generate_random_key("01234")
zan_key = generate_random_key("01")
collect_key = generate_random_key("0")
follow_key = generate_random_key("012")
comment_read = generate_random_key("01234")

print(enter_key, zan_key, collect_key, follow_key, comment_read)

# 新增养号端点：接收关键词和会员卡号，生成随机参数并记录养号信息
@app.route('/get_养号_params', methods=['POST'])
def get_养号_params():
    data = request.get_json()
    logging.info(f"接收到的养号请求: {data}")

    if not data:
        logging.error("养号请求失败 - 无效的 JSON 数据")
        return jsonify({'error': '无效的 JSON 数据'}), 400

    member_id = str(data.get('card_id')) if data.get('card_id') is not None else None
    keywords = data.get('keywords')

    if member_id is None or keywords is None:
        logging.error(f"缺少必要数据 - 会员ID: {member_id}, 关键词: {keywords}")
        return jsonify({'error': '缺少必要数据'}), 400

    # 校验会员有效性并扣减下载次数
    if not is_valid_member(member_id):
        logging.error(f"未授权访问 - 会员ID: {member_id}")
        return jsonify({'error': '未授权访问'}), 403

    # 扣减下载次数
    membership_data[member_id]['download_count'] -= 1
    logging.info(f"会员ID: {member_id} 的下载次数已扣减，剩余下载次数: {membership_data[member_id]['download_count']}")

    # 更新养号关键词和次数
    if member_id not in 养号_keywords_data:
        养号_keywords_data[member_id] = []

    # 添加关键词，去重并排序
    if isinstance(keywords, list):
        养号_keywords_data[member_id].extend(keywords)
    else:
        养号_keywords_data[member_id].append(keywords)
    养号_keywords_data[member_id] = sorted(set(养号_keywords_data[member_id]))

    # 累加养号次数
    membership_data[member_id]['养号_total_downloads'] = membership_data[member_id].get('养号_total_downloads', 0) + 1
    logging.info(f"会员ID: {member_id} 的养号关键词已更新: {养号_keywords_data[member_id]}")
    logging.info(f"会员ID: {member_id} 的养号总次数更新为: {membership_data[member_id]['养号_total_downloads']}")

    # 生成并返回随机参数
    养号_params = generate_养号_params(keywords)
    save_data()  # 保存数据
    return jsonify(养号_params), 200

# 保存数据的函数，支持养号数据的存储
def save_data():
    try:
        # 确保关键词去重和排序
        for member_id in keywords_data:
            keywords_data[member_id] = sorted(set(keywords_data[member_id]))
        for member_id in data_keywords_data:
            data_keywords_data[member_id] = sorted(set(data_keywords_data[member_id]))
        for member_id in 养号_keywords_data:
            养号_keywords_data[member_id] = sorted(set(养号_keywords_data[member_id]))

        # 写入 CSV 文件
        with open(DATA_FILE, mode='w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(['会员ID', '有效期至', '下载次数', '图文下载关键词', '图文下载总次数', '搜索数据关键词', '搜索数据总下载次数', '养号关键词', '养号总次数'])
            for member_id, data in membership_data.items():
                member_id = str(member_id)
                expiry_date = data.get('expiry_date', 'None')
                download_count = data.get('download_count', 0)
                download_keywords = ';'.join(keywords_data.get(member_id, []))
                data_keywords = ';'.join(data_keywords_data.get(member_id, []))
                养号_keywords = ';'.join(养号_keywords_data.get(member_id, []))
                total_downloads = data.get('total_downloads', 0)
                data_total_downloads = data.get('data_total_downloads', 0)
                养号_total_downloads = data.get('养号_total_downloads', 0)
                writer.writerow([member_id, expiry_date, download_count, download_keywords, total_downloads, data_keywords, data_total_downloads, 养号_keywords, 养号_total_downloads])
        logging.info("会员数据已保存")
    except PermissionError as e:
        logging.error(f"保存失败: {e}")
        raise

# 加载数据时增加养号关键词和养号总次数的加载
def load_data():
    global membership_data, keywords_data, data_keywords_data, 养号_keywords_data, total_downloads
    membership_data = {}
    keywords_data = {}
    data_keywords_data = {}
    养号_keywords_data = {}
    total_downloads = 0
    data_total_downloads = 0
    养号_total_downloads = 0
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, mode='r', newline='') as file:
            reader = csv.DictReader(file)
            for row in reader:
                member_id = str(row['会员ID'])
                membership_data[member_id] = {
                    'expiry_date': row['有效期至'] if row['有效期至'] != 'None' else None,
                    'download_count': int(row['下载次数']),
                    'total_downloads': int(row.get('图文下载总次数', 0)),
                    'data_total_downloads': int(row.get('搜索数据总下载次数', 0)),
                    '养号_total_downloads': int(row.get('养号总次数', 0))
                }
                keywords_data[member_id] = row['图文下载关键词'].split(';') if row['图文下载关键词'] else []
                data_keywords_data[member_id] = row['搜索数据关键词'].split(';') if row['搜索数据关键词'] else []
                养号_keywords_data[member_id] = row['养号关键词'].split(';') if row['养号关键词'] else []
    logging.info("会员数据已加载")
    logging.info("图文关键词数据已加载: {}".format(keywords_data))
    logging.info("搜索数据关键词数据已加载: {}".format(data_keywords_data))
    logging.info("养号关键词数据已加载: {}".format(养号_keywords_data))

# 加载数据
load_data()



# 判断是否为有效会员
def is_valid_member(member_id):
    member_id = str(member_id)
    if member_id in membership_data:
        expiry_date = membership_data[member_id].get('expiry_date')
        download_count = membership_data[member_id].get('download_count', 0)

        # 确保下载次数不为负数
        if download_count < 0:
            membership_data[member_id]['download_count'] = 0
            download_count = 0

        # 如果有效期为空，允许下载
        if not expiry_date or expiry_date == 'None':
            logging.info(f"会员ID: {member_id} 有效期为空，允许下载")
            return True

        # 尝试解析有效期
        try:
            # 支持多种日期格式
            date_formats = [
                '%Y-%m-%d %H:%M:%S',
                '%Y/%m/%d %H:%M',
                '%Y-%m-%d',
                '%Y/%m/%d'
            ]
            
            parsed_date = None
            for date_format in date_formats:
                try:
                    parsed_date = datetime.strptime(str(expiry_date), date_format)
                    logging.info(f"成功解析日期 - 会员ID: {member_id}, 格式: {date_format}")
                    break
                except ValueError:
                    continue
            
            if parsed_date is None:
                logging.error(f"无法解析日期 - 会员ID: {member_id}, 有效期: {expiry_date}")
                return False

            # 检查有效期是否已过
            if parsed_date > datetime.now():
                logging.info(f"会员ID: {member_id} 有效期内，允许下载")
                return True
            else:
                # 有效期已过，检查下载次数
                if download_count > 0:
                    logging.warning(f"会员ID: {member_id} 的有效期已过，但由于剩余下载次数，允许下载")
                    return True
                else:
                    logging.error(f"未授权访问 - 会员ID: {member_id}, 原因: 下载次数为0")
                    return False

        except Exception as e:
            logging.error(f"日期处理错误 - 会员ID: {member_id}, 有效期: {expiry_date}, 错误: {str(e)}")
            return False

    logging.error(f"未授权访问 - 会员ID: {member_id}, 原因: 找不到会员ID")
    return False



# 获取"搜索数据关键词"的端点
@app.route('/get_data_keywords', methods=['POST'])
def get_data_keywords():
    data = request.get_json()
    logging.info(f"接收到的数据关键词获取请求: {data}")

    if not data:
        logging.error("数据关键词获取失败 - 无效的 JSON 数据")
        return jsonify({'error': '无效的 JSON 数据'}), 400

    member_id = str(data.get('card_id')) if data.get('card_id') is not None else None
    keywords = data.get('keywords')

    if member_id is None or keywords is None:
        logging.error(f"缺少必要数据 - 会员ID: {member_id}, 关键词: {keywords}")
        return jsonify({'error': '缺少必要数据'}), 400

    # 校验会员有效性并扣减下载次数
    if not is_valid_member(member_id):
        logging.error(f"未授权访问 - 会员ID: {member_id}")
        return jsonify({'error': '未授权访问'}), 403

    # 扣减下载次数
    membership_data[member_id]['download_count'] -= 1
    logging.info(f"会员ID: {member_id} 的下载次数已扣减，剩余下载次数: {membership_data[member_id]['download_count']}")

    # 更新并记录"搜索数据关键词"
    if member_id not in data_keywords_data:
        data_keywords_data[member_id] = []
        
    # 确保 keywords 是列表格式
    if isinstance(keywords, list):
        data_keywords_data[member_id].extend(keywords)
    else:
        data_keywords_data[member_id].append(keywords)  # 如果是字符串则直接添加
    
    # 去重并排序关键词列表
    data_keywords_data[member_id] = sorted(set(data_keywords_data[member_id]))
    logging.info(f"会员ID: {member_id} 的数据关键词已更新: {data_keywords_data[member_id]}")

    # 增加"搜索数据总下载次数"
    membership_data[member_id]['data_total_downloads'] = membership_data[member_id].get('data_total_downloads', 0) + 1

    # 保存数据
    save_data()
    return jsonify({'message': '数据关键词记录成功'}), 200




@app.route('/save', methods=['POST'])
def save_membership():
    try:
        data = request.get_json()
        logging.info(f"接收到的数据: {data}")
        if not data:
            return jsonify({'error': 'Invalid JSON data'}), 400

        member_id = str(data.get('card_id')) if data.get('card_id') is not None else None
        validity_period = data.get('expiry_days')
        download_count = data.get('remaining_downloads')
        huiyuan = data.get('huiyuan')

        if isinstance(validity_period, str) and re.match(r'{{.*}}', validity_period):
            logging.error("收到未替换的模板字符串 - validity_period")
            return jsonify({'error': 'Template variable not replaced for validity_period'}), 400
        if isinstance(download_count, str) and re.match(r'{{.*}}', download_count):
            logging.error("收到未替换的模板字符串 - download_count")
            return jsonify({'error': 'Template variable not replaced for download_count'}), 400

        if member_id is None or validity_period is None or download_count is None or huiyuan is None:
            logging.error(f"Missing data - member_id: {member_id}, validity_period: {validity_period}, download_count: {download_count}, huiyuan: {huiyuan}")
            return jsonify({'error': 'Missing data'}), 400

        try:
            validity_period = int(float(validity_period))
            download_count = int(float(download_count))
        except (ValueError, TypeError):
            logging.error(f"数据类型转换错误 - validity_period: {validity_period}, download_count: {download_count}")
            return jsonify({'error': 'Invalid data type for validity_period or download_count'}), 400

        if member_id in membership_data:
            existing_expiry_date = membership_data[member_id].get('expiry_date')
            if existing_expiry_date and existing_expiry_date != 'None':
                try:
                    # 支持多种日期格式
                    date_formats = [
                        '%Y-%m-%d %H:%M:%S',
                        '%Y/%m/%d %H:%M',
                        '%Y-%m-%d',
                        '%Y/%m/%d'
                    ]
                    
                    parsed_date = None
                    for date_format in date_formats:
                        try:
                            parsed_date = datetime.strptime(str(existing_expiry_date), date_format)
                            break
                        except ValueError:
                            continue
                    
                    if parsed_date is None:
                        parsed_date = datetime.now()
                        
                    new_expiry_date = parsed_date + timedelta(days=validity_period)
                    expiry_date_str = new_expiry_date.strftime('%Y-%m-%d %H:%M:%S')
                except Exception as e:
                    logging.error(f"日期处理错误: {e}")
                    expiry_date_str = (datetime.now() + timedelta(days=validity_period)).strftime('%Y-%m-%d %H:%M:%S')
            else:
                expiry_date_str = (datetime.now() + timedelta(days=validity_period)).strftime('%Y-%m-%d %H:%M:%S')
            
            membership_data[member_id]['expiry_date'] = expiry_date_str
            membership_data[member_id]['download_count'] += download_count
            membership_data[member_id]['count'] = membership_data[member_id].get('count', 0) + 1
        else:
            expiry_date_str = None
            if validity_period > 0:
                expiry_date = datetime.now() + timedelta(days=validity_period)
                expiry_date_str = expiry_date.strftime('%Y-%m-%d %H:%M:%S')

            membership_data[member_id] = {
                'expiry_date': expiry_date_str,
                'download_count': download_count,
                'count': 1
            }

        save_data()
        logging.info(f"保存成功 - 卡号: {member_id}, 有效期截止日期: {membership_data[member_id]['expiry_date']}, 下载次数: {membership_data[member_id]['download_count']}, 执行次数: {membership_data[member_id]['count']}")
        return jsonify({'message': 'Data saved successfully'}), 200

    except Exception as e:
        logging.error(f"保存失败: {e}")
        return jsonify({'error': 'Failed to save data'}), 500


def download_and_compress_image(image_url, quality=70, resize_scale=0.7):
    import logging
    try:
        # 增加请求头，防止防盗链
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Referer": "https://www.xiaohongshu.com/"
        }
        response = requests.get(image_url, headers=headers)
        response.raise_for_status()
        content_type = response.headers.get('Content-Type', '')
        logging.info(f"下载图片: {image_url}, Content-Type: {content_type}, 状态码: {response.status_code}")

        image = None
        # 先尝试用PIL打开
        try:
            image = Image.open(BytesIO(response.content))
            image.load()  # 强制加载，触发异常
            logging.info(f"PIL成功打开图片, 格式: {image.format}")
        except Exception as pil_e:
            logging.warning(f"PIL无法打开图片，尝试用imageio兜底: {pil_e}")
            try:
                import imageio.v3 as iio
                import numpy as np
                arr = iio.imread(response.content, extension=".webp")
                image = Image.fromarray(arr)
                logging.info("imageio成功读取webp图片")
            except Exception as imageio_e:
                logging.error(f"imageio也无法打开图片: {imageio_e}")
                # 打印前100字节内容，便于排查
                logging.error(f"图片内容前100字节: {response.content[:100]}")
                return None

        # 压缩和保存
        image = image.convert('RGB')  # 保证能保存为JPEG
        image = image.resize((int(image.width * resize_scale), int(image.height * resize_scale)), Image.LANCZOS)
        buffer = BytesIO()
        image.save(buffer, format="JPEG", quality=quality)
        buffer.seek(0)
        return list(buffer.read())
    except Exception as e:
        logging.error(f"处理图片时出错: {e}")
        return None



@app.route('/upload', methods=['POST'])
def upload():
    global total_downloads
    data = request.get_json()
    logging.info(f"接收到的上传请求: {data}")  # 打印接收到的数据进行调试
    if not data:
        logging.error("上传失败 - 无效的JSON数据")
        return jsonify({'error': '无效的JSON数据'}), 400

    member_id = str(data.get('card_id')) if data.get('card_id') is not None else None
    sheet_id = data.get('sheetId')
    values = data.get('values')
    access_token = data.get('access_token')
    sheet_range = data.get('sheet_id')  # sheet_id代表工作表的ID
    keywords = data.get('keywords')

    # 打印所有提取的数据，确认接收无误
    logging.info(f"解析的数据 - sheet_id: {sheet_id}, values: {values}, access_token: {access_token}, sheet_range: {sheet_range}, member_id: {member_id}, keywords: {keywords}")

    # 如果不是有效会员，拒绝执行
    if not is_valid_member(member_id):
        logging.error(f"未授权访问 - 会员ID: {member_id}")
        return jsonify({'error': '未授权访问'}), 403

    # 扣减下载次数
    membership_data[member_id]['download_count'] -= 1
    membership_data[member_id]['total_downloads'] = membership_data[member_id].get('total_downloads', 0) + 1
    total_downloads += 1
    logging.info(f"会员ID: {member_id} 的下载次数已扣减，剩余下载次数: {membership_data[member_id]['download_count']}，总下载次数: {total_downloads}")

    # 保存关键词数据并去重
    if member_id not in keywords_data:
        keywords_data[member_id] = []
    
    # 确保 keywords 为列表格式
    if isinstance(keywords, list):
        keywords_data[member_id].extend(keywords)
    else:
        keywords_data[member_id].append(keywords)  # 如果是字符串，则直接添加

    keywords_data[member_id] = sorted(set(keywords_data[member_id]))  # 去重并排序关键词
    logging.info(f"会员ID: {member_id} 的关键词已更新: {keywords_data[member_id]}")

    save_data()

    # 将一维数组转换为二维数组
    if isinstance(values, list) and all(not isinstance(i, list) for i in values):
        values = [values]

    # 确保参数齐全
    if sheet_id and values and access_token and sheet_range:
        # 使用 values_append 自动追加到表格的末尾
        feishu_request_body = {
            "valueRange": {
                "range": f"{sheet_range}!A1:L1",  # 使用传递的 sheet_range 来表示工作表 ID，并设置一个适当的范围
                "values": values
            }
        }

        # 设置飞书 API 的请求 URL 和 headers
        feishu_api_url = f"https://open.feishu.cn/open-apis/sheets/v2/spreadsheets/{sheet_id}/values_append?insertDataOption=INSERT_ROWS"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }

        # 调用飞书 API，使用 POST 方法进行追加写入
        try:
            logging.info(f"开始向飞书 API 发送请求: URL={feishu_api_url}, 数据={feishu_request_body}")
            response = requests.post(feishu_api_url, headers=headers, json=feishu_request_body)
            response.raise_for_status()  # 如果响应状态码是 4xx 或 5xx，抛出 HTTPError 异常

            # 打印飞书 API 的响应
            logging.info(f"飞书 API 响应: {response.status_code}, {response.text}")

            # 返回成功消息
            return jsonify({'message': '数据已成功发送到飞书 API!'}), 200
        except requests.exceptions.RequestException as e:
            # 处理请求错误
            logging.error(f"发送数据到飞书 API 失败: {e}")
            return jsonify({'error': '发送数据到飞书 API 失败'}), 500
    else:
        logging.error(f"缺少必要字段 - sheet_id: {sheet_id}, values: {values}, access_token: {access_token}, sheet_range: {sheet_range}")
        return jsonify({'error': '缺少必要字段!'}), 400


def get_empty_row(access_token, sheet_value, sheet_id):
    url = f"https://open.feishu.cn/open-apis/sheets/v2/spreadsheets/{sheet_value}/values_batch_get"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    params = {
        "ranges": f"{sheet_id}!M:M",
        "valueRenderOption": "ToString",
        "dateTimeRenderOption": "FormattedString"
    }

    response = requests.get(url, headers=headers, params=params)
    if response.status_code == 200:
        data = response.json()
        values = data.get("data", {}).get("valueRanges", [])[0].get("values", [])

        # 找到第一个空行的行号
        for i, row in enumerate(values, start=1):
            if not row or row[0] is None:
                return i  # 返回第一个空行的行号
        return len(values) + 1  # 如果 M 列已填满，返回下一行号
    else:
        raise Exception("获取表格数据失败")



@app.route('/upload-images', methods=['POST'])
def upload_images():
    data = request.get_json()
    logging.info(f"接收到的上传图片请求: {data}")  # 打印接收到的数据进行调试
    
    member_id = str(data.get('card_id')) if data.get('card_id') is not None else None
    image_urls = list(dict.fromkeys(data.get('image_urls', [])))  # 去重并保持顺序
    if image_urls:
        # 将第一张图片放到最后
        logging.info("调整图片顺序，将第一张图片放到最后")
        image_urls.append(image_urls.pop(0))
    
    sheet_value = data.get('sheet_value')
    sheet_id = data.get('sheet_id')
    access_token = data.get('access_token')
    
    if not (image_urls and sheet_value and sheet_id and access_token):
        logging.error("缺少必要的参数")
        return jsonify({"error": "缺少必要的参数"}), 400

    current_column = "M"  # 从M列开始
    try:
        row_number = get_empty_row(access_token, sheet_value, sheet_id)
        logging.info(f"找到第一个空行的行号: {row_number}")
    except Exception as e:
        logging.error(f"获取空行失败: {e}")
        return jsonify({"error": "获取空行失败"}), 500
    
    results = []
    for url in image_urls:
        # 下载并压缩图片
        logging.info(f"开始下载并压缩图片: {url}")
        compressed_image_data = download_and_compress_image(url)
        if compressed_image_data is None:
            logging.error(f"图片压缩失败: {url}")
            results.append({"url": url, "status": "failed", "message": "图片压缩失败"})
            continue

        # 设置飞书API上传请求
        upload_url = f"https://open.feishu.cn/open-apis/sheets/v2/spreadsheets/{sheet_value}/values_image"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        payload = {
            "range": f"{sheet_id}!{current_column}{row_number}:{current_column}{row_number}",
            "image": compressed_image_data,
            "name": f"image_{url.split('/')[-1]}.jpg"
        }

        try:
            logging.info(f"开始上传图片到飞书: {payload['name']}")
            response = requests.post(upload_url, headers=headers, json=payload)
            response.raise_for_status()
            logging.info(f"图片上传成功: {url}")
            results.append({"url": url, "status": "success"})
            current_column = chr(ord(current_column) + 1)  # 切换到下一列
        except requests.exceptions.RequestException as e:
            logging.error(f"上传图片到飞书失败: {e}")
            results.append({"url": url, "status": "failed", "message": str(e)})

    return jsonify({"results": results})



# ========================================
# AI交易系统监控端点
# ========================================

TRADING_DATA_BASE = '/root/10-23-bot/ds/trading_data'

def get_trading_data_dir(model='deepseek'):
    """根据模型名称获取数据目录"""
    if model not in ['deepseek', 'qwen']:
        model = 'deepseek'  # 默认DeepSeek
    return os.path.join(TRADING_DATA_BASE, model)

def get_pause_reason(pause_level):
    """根据暂停等级返回原因描述"""
    if pause_level == 0:
        return ''
    elif pause_level == 1:
        return '连续3笔亏损，2小时冷静期'
    elif pause_level == 2:
        return '再连续2笔亏损，4小时冷静期'
    elif pause_level == 3:
        return '再连续2笔亏损，暂停至明日'
    else:
        return f'冷静期等级{pause_level}'

CHAT_HISTORY_FILE = os.path.join(TRADING_DATA_BASE, 'web_chat_history.json')

# 系统控制密码（用于AI对话和模式切换）
CONTROL_PASSWORD = '34801198Bai'

# 访客统计文件
VISITOR_LOG_FILE = os.path.join(TRADING_DATA_BASE, 'visitor_ips.txt')

def log_visitor():
    """记录访客IP"""
    try:
        # 获取真实IP（考虑反向代理）
        if request.headers.get('X-Forwarded-For'):
            client_ip = request.headers.get('X-Forwarded-For').split(',')[0].strip()
        elif request.headers.get('X-Real-IP'):
            client_ip = request.headers.get('X-Real-IP')
        else:
            client_ip = request.remote_addr
        
        # 读取已记录的IP
        existing_ips = set()
        if os.path.exists(VISITOR_LOG_FILE):
            with open(VISITOR_LOG_FILE, 'r') as f:
                existing_ips = set(line.strip() for line in f if line.strip())
        
        # 如果是新IP，追加记录
        if client_ip not in existing_ips:
            with open(VISITOR_LOG_FILE, 'a') as f:
                f.write(f"{client_ip}\n")
            return len(existing_ips) + 1
        else:
            return len(existing_ips)
    except Exception as e:
        logging.error(f"记录访客失败: {e}")
        return 0

def get_visitor_count():
    """获取独立访客数量"""
    try:
        if os.path.exists(VISITOR_LOG_FILE):
            with open(VISITOR_LOG_FILE, 'r') as f:
                return len([line for line in f if line.strip()])
        return 0
    except:
        return 0

@app.route('/trading-visitor-count', methods=['GET'])
def trading_visitor_count():
    """获取访客数量"""
    try:
        count = get_visitor_count()
        return jsonify({'count': count}), 200
    except Exception as e:
        logging.error(f"获取访客数失败: {e}")
        return jsonify({'count': 0}), 200

@app.route('/trading-status', methods=['GET'])
def trading_status():
    """获取交易系统状态"""
    try:
        model = request.args.get('model', 'deepseek')  # 获取model参数
        data_dir = get_trading_data_dir(model)
        status_file = os.path.join(data_dir, 'system_status.json')
        if os.path.exists(status_file):
            with open(status_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return jsonify(data), 200
        else:
            return jsonify({'error': '系统状态文件不存在'}), 404
    except Exception as e:
        logging.error(f"读取交易状态失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/trading-positions', methods=['GET'])
def trading_positions():
    """获取当前持仓（适配中英文字段名，支持时间筛选）"""
    try:
        model = request.args.get('model', 'deepseek')
        # 🔥 获取时间周期参数
        range_type = request.args.get('range', 'all')
        start_date = request.args.get('start_date', '')
        end_date = request.args.get('end_date', '')
        
        data_dir = get_trading_data_dir(model)
        positions_file = os.path.join(data_dir, 'current_positions.csv')
        if os.path.exists(positions_file):
            with open(positions_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                raw_positions = list(reader)
            
            # 🔥 根据开仓时间筛选持仓
            filtered_positions = filter_data_by_time_range(
                raw_positions, '开仓时间', range_type, start_date, end_date
            )
            
            # 转换中文字段名为英文（包含完整的交易信息）
            positions = []
            for pos in filtered_positions:
                positions.append({
                    'symbol': pos.get('币种', pos.get('symbol', '')),
                    'side': pos.get('方向', pos.get('side', '')),
                    'size': float(pos.get('数量', pos.get('size', 0)) or 0),
                    'entry_price': float(pos.get('开仓价', pos.get('entry_price', 0)) or 0),
                    'unrealized_pnl': float(pos.get('当前盈亏(U)', pos.get('unrealized_pnl', 0)) or 0),
                    # 【新增】完整的交易信息（部分平仓后仍保留）
                    'open_time': pos.get('开仓时间', ''),
                    'leverage': float(pos.get('杠杆', pos.get('leverage', 1)) or 1),
                    'margin': float(pos.get('保证金(U)', pos.get('margin', 0)) or 0),
                    'stop_loss': float(pos.get('止损', pos.get('stop_loss', 0)) or 0),
                    'take_profit': float(pos.get('止盈', pos.get('take_profit', 0)) or 0),
                    'risk_reward': float(pos.get('盈亏比', pos.get('risk_reward', 0)) or 0),
                    'open_reason': pos.get('开仓理由', pos.get('open_reason', ''))
                })
            return jsonify({'positions': positions}), 200
        else:
            return jsonify({'positions': []}), 200
    except Exception as e:
        logging.error(f"读取持仓数据失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/trading-history', methods=['GET'])
def trading_history():
    """获取交易历史（支持时间筛选，以平仓时间为准）"""
    try:
        model = request.args.get('model', 'deepseek')
        data_dir = get_trading_data_dir(model)
        limit = int(request.args.get('limit', 9999))  # 默认返回20条
        # 🔥 获取时间周期参数
        range_type = request.args.get('range', 'all')
        start_date = request.args.get('start_date', '')
        end_date = request.args.get('end_date', '')
        
        trades_file = os.path.join(data_dir, 'trades_history.csv')
        if os.path.exists(trades_file):
            with open(trades_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                all_trades = list(reader)
            
            # 🔥 根据平仓时间筛选交易（只显示已平仓的交易）
            closed_trades = [t for t in all_trades if t.get('平仓时间')]
            filtered_trades = filter_data_by_time_range(
                closed_trades, '平仓时间', range_type, start_date, end_date
            )
            
            # 🔥 限制返回数量（取最近的N条）
            if len(filtered_trades) > limit:
                # 按平仓时间排序，取最新的
                filtered_trades = sorted(filtered_trades, key=lambda x: x.get('平仓时间', ''), reverse=True)[:limit]
            
            return jsonify({'trades': filtered_trades}), 200
        else:
            return jsonify({'trades': []}), 200
    except Exception as e:
        logging.error(f"读取交易历史失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/trading-pnl', methods=['GET'])
def trading_pnl():
    """获取盈亏曲线数据（支持日期范围筛选）"""
    try:
        model = request.args.get('model', 'deepseek')
        data_dir = get_trading_data_dir(model)
        limit = int(request.args.get('limit', 9999))
        range_type = request.args.get('range', 'all')  # day/week/month/all
        start_date = request.args.get('start_date', '')  # YYYY-MM-DD
        end_date = request.args.get('end_date', '')  # YYYY-MM-DD
        
        pnl_file = os.path.join(data_dir, 'pnl_history.csv')
        if os.path.exists(pnl_file):
            with open(pnl_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                if len(lines) <= 1:
                    return jsonify({'pnl_data': []}), 200
                
                # 解析所有数据
                reader = csv.DictReader(lines)
                all_data = list(reader)
                
                # 根据日期范围筛选（使用北京时间 UTC+8）
                from datetime import timezone
                beijing_tz = timezone(timedelta(hours=8))
                now_beijing = datetime.now(beijing_tz).replace(tzinfo=None)  # 获取北京时间并移除时区信息
                filtered_data = []
                
                # 计算时间范围的起始时间（北京时间）
                if range_type == 'day':
                    # 当天 00:00 开始（北京时间）
                    start_time = now_beijing.replace(hour=0, minute=0, second=0, microsecond=0)
                elif range_type == 'week':
                    # 本周一 00:00 开始（北京时间）
                    days_since_monday = now_beijing.weekday()
                    start_time = (now_beijing - timedelta(days=days_since_monday)).replace(hour=0, minute=0, second=0, microsecond=0)
                elif range_type == 'month':
                    # 本月1号 00:00 开始（北京时间）
                    start_time = now_beijing.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                elif start_date and end_date:
                    # 指定日期范围
                    start_time = datetime.strptime(start_date, '%Y-%m-%d')
                    end_time = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
                else:
                    start_time = None
                
                for row in all_data:
                    timestamp_utc = row.get('时间') or row.get('timestamp', '')
                    if not timestamp_utc:
                        continue
                    
                    try:
                        # UTC时间转换为北京时间
                        utc_time = datetime.strptime(timestamp_utc, '%Y-%m-%d %H:%M:%S')
                        beijing_time = utc_time + timedelta(hours=8)
                        
                        # 更新row中的时间为北京时间
                        row['时间'] = beijing_time.strftime('%Y-%m-%d %H:%M:%S')
                        if 'timestamp' in row:
                            row['timestamp'] = beijing_time.strftime('%Y-%m-%d %H:%M:%S')
                    except:
                        continue
                    
                    # 按范围类型筛选（使用北京时间）
                    if range_type in ['day', 'week', 'month']:
                        if beijing_time >= start_time:
                            filtered_data.append(row)
                    elif start_date and end_date:
                        if start_time <= beijing_time < end_time:
                            filtered_data.append(row)
                    else:
                        # 全部数据
                        filtered_data.append(row)
                
                # "全部"显示所有历史数据，不受limit限制
                # 其他范围类型如果数据过多，保留最后limit条以提升性能
                if range_type != 'all' and len(filtered_data) > limit:
                    filtered_data = filtered_data[-limit:]
                
                return jsonify({'pnl_data': filtered_data}), 200
        else:
            return jsonify({'pnl_data': []}), 200
    except Exception as e:
        logging.error(f"读取盈亏数据失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/trading-ai-decisions', methods=['GET'])
def trading_ai_decisions():
    """获取AI决策历史（最近N条）"""
    try:
        model = request.args.get('model', 'deepseek')
        data_dir = get_trading_data_dir(model)
        limit = int(request.args.get('limit', 9999))
        decisions_file = os.path.join(data_dir, 'ai_decisions.json')
        if os.path.exists(decisions_file):
            with open(decisions_file, 'r', encoding='utf-8') as f:
                decisions = json.load(f)
                # 返回最后N条
                if isinstance(decisions, list):
                    decisions = decisions[-limit:]
                return jsonify({'decisions': decisions}), 200
        else:
            return jsonify({'decisions': []}), 200
    except Exception as e:
        logging.error(f"读取AI决策失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/trading-summary', methods=['GET'])
def trading_summary():
    """获取交易摘要（一次性返回所有关键信息）"""
    try:
        model = request.args.get('model', 'deepseek')
        # 🔥 获取时间周期参数
        range_type = request.args.get('range', 'all')
        start_date = request.args.get('start_date', '')
        end_date = request.args.get('end_date', '')
        
        data_dir = get_trading_data_dir(model)
        summary = {}
        
        # 系统状态（适配中英文字段名）
        status_file = os.path.join(data_dir, 'system_status.json')
        trades_file = os.path.join(data_dir, 'trades_history.csv')
        
        # 初始化all_trades，避免作用域问题
        all_trades = []
        
        if os.path.exists(status_file):
            with open(status_file, 'r', encoding='utf-8') as f:
                raw_status = json.load(f)
                
                # 读取所有交易记录（重新赋值，覆盖外部初始化）
                all_trades = []
                if os.path.exists(trades_file):
                    try:
                        with open(trades_file, 'r', encoding='utf-8') as tf:
                            trades_reader = csv.DictReader(tf)
                            trades_reader.fieldnames = [name.strip() if name else name for name in trades_reader.fieldnames]
                            for trade in trades_reader:
                                trade_cleaned = {k.strip() if k else k: v for k, v in trade.items()}
                                all_trades.append(trade_cleaned)
                            logging.info(f"[{model}] 读取到 {len(all_trades)} 笔交易记录")
                    except Exception as e:
                        logging.error(f"读取交易历史失败: {e}")
                
                # 🔥 时间周期过滤：过滤已平仓的交易
                closed_trades = [t for t in all_trades if t.get('平仓时间') and t.get('平仓时间').strip()]
                logging.info(f"[{model}] 已平仓交易数: {len(closed_trades)}, 时间范围: {range_type}")
                
                filtered_closed_trades = filter_data_by_time_range(
                    closed_trades, '平仓时间', range_type, start_date, end_date
                )
                logging.info(f"[{model}] 筛选后已平仓交易数: {len(filtered_closed_trades)}")
                
                # 计算总已实现盈亏和胜率（基于过滤后的交易）
                total_realized_pnl = 0
                win_count = 0
                total_count = len(filtered_closed_trades)
                
                for trade in filtered_closed_trades:
                    pnl_str = trade.get('盈亏(U)', '0') or '0'
                    try:
                        pnl = float(pnl_str)
                        total_realized_pnl += pnl
                        if pnl > 0:
                            win_count += 1
                    except (ValueError, TypeError):
                        continue
                
                # 计算胜率
                win_rate = (win_count / total_count * 100) if total_count > 0 else 0
                logging.info(f"[{model}] 胜率: {win_rate:.1f}% ({win_count}/{total_count})")
                
                # 读取盈亏历史数据（用于计算夏普比率）
                pnl_history = []
                pnl_file = os.path.join(data_dir, 'pnl_history.csv')
                if os.path.exists(pnl_file):
                    try:
                        with open(pnl_file, 'r', encoding='utf-8') as pf:
                            pnl_reader = csv.DictReader(pf)
                            pnl_history = list(pnl_reader)
                            pnl_history = filter_data_by_time_range(
                                pnl_history, '时间', range_type, start_date, end_date
                            )
                    except Exception as e:
                        logging.error(f"读取盈亏历史失败: {e}")
                
                # 计算未实现盈亏（当前持仓的盈亏，不受时间筛选影响）
                unrealized_pnl = 0
                
                # 计算指标
                initial_capital = 100.0
                total_assets = raw_status.get('总资产', raw_status.get('total_assets', 0))
                
                # 🔥 根据时间周期计算实际盈利和年化收益
                if range_type == 'all':
                    profit_rate = ((total_assets - initial_capital) / initial_capital * 100) if initial_capital > 0 else 0
                else:
                    profit_rate = (total_realized_pnl / initial_capital * 100) if initial_capital > 0 else 0
                
                # 计算年化收益率
                annualized_return = 0
                if filtered_closed_trades:
                    try:
                        sorted_trades = sorted(filtered_closed_trades, key=lambda x: x.get('开仓时间', ''))
                        first_trade = sorted_trades[0]
                        start_time = datetime.strptime(first_trade.get('开仓时间', ''), '%Y-%m-%d %H:%M:%S')
                        days_elapsed = (datetime.now() - start_time).total_seconds() / 86400
                        if days_elapsed > 0:
                            annualized_return = ((profit_rate / 100 + 1) ** (365 / days_elapsed) - 1) * 100
                    except Exception as e:
                        logging.error(f"计算年化收益失败: {e}")
                
                # 🔥 计算最大回撤
                max_drawdown = calculate_max_drawdown(filtered_closed_trades)
                
                # 🔥 计算夏普比率
                sharpe_ratio = calculate_sharpe_ratio(
                    filtered_closed_trades,
                    pnl_history if pnl_history else None,
                    initial_capital
                )
                
                # 计算总保证金占用（从positions中获取）
                total_margin = 0
                
                # 转换中文字段名为英文
                summary['status'] = {
                    'timestamp': utc_to_beijing_time(raw_status.get('更新时间', raw_status.get('timestamp', ''))),  # UTC→北京时间
                    'usdt_balance': 0,  # 先占位，后面会重新计算
                    'total_assets': total_assets,
                    'total_position_value': raw_status.get('总仓位价值', raw_status.get('total_position_value', 0)),
                    'unrealized_pnl': unrealized_pnl,
                    'total_realized_pnl': total_realized_pnl,
                    'profit_rate': profit_rate,  # 盈利比例
                    'annualized_return': annualized_return,  # 年化收益率
                    'max_drawdown': max_drawdown,  # 🔥 最大回撤
                    'sharpe_ratio': sharpe_ratio,  # 🔥 夏普比率
                    'win_rate': win_rate,  # 🔥 胜率
                    'win_count': win_count,  # 盈利交易数
                    'total_trades': total_count,  # 总交易数
                    'max_position': raw_status.get('最大仓位限制', 100),
                    'position_count': raw_status.get('当前持仓数', 0),
                    'positions_detail': raw_status.get('持仓详情', []),
                    'market_overview': raw_status.get('市场概况', []),
                    'ai_analysis': raw_status.get('AI分析', ''),
                    'risk_assessment': raw_status.get('风险评估', '')
                }
        
        # 实验配置信息
        summary['experiment_config'] = {
            'initial_capital': 100.0,
            'trading_pairs': ['BTC', 'ETH', 'SOL', 'BNB', 'XRP', 'DOGE', 'LTC'],
            'max_leverage': '≤5x (合约)',
            'strategy': 'AI智能多空策略 + 裸K分析',
            'risk_per_trade': '单笔最大40U'
        }
        
        # 当前持仓（适配中英文字段名）
        positions_file = os.path.join(data_dir, 'current_positions.csv')
        trades_file = os.path.join(data_dir, 'trades_history.csv')
        if os.path.exists(positions_file):
            with open(positions_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                raw_positions = list(reader)
                # 从trades_history.csv读取开仓时间、止损、止盈等信息
                trade_details = {}
                if os.path.exists(trades_file):
                    with open(trades_file, 'r', encoding='utf-8') as tf:
                        trades_reader = csv.DictReader(tf)
                        for trade in trades_reader:
                            if not trade.get('平仓时间'):  # 未平仓
                                key = f"{trade.get('币种', '')}_{trade.get('方向', '')}"
                                trade_details[key] = {
                                    'open_time': trade.get('开仓时间', ''),
                                    'stop_loss': float(trade.get('止损', 0) or 0),
                                    'take_profit': float(trade.get('止盈', 0) or 0),
                                    'risk_reward': float(trade.get('盈亏比', 0) or 0),
                                    'margin': float(trade.get('仓位(U)', 0) or 0),  # 保证金
                                    'leverage': int(trade.get('杠杆率', 1) or 1),
                                    'open_reason': trade.get('开仓理由', '')
                                }
                # 转换字段名
                summary['positions'] = []
                for pos in raw_positions:
                    coin = pos.get('币种', pos.get('symbol', ''))
                    side = pos.get('方向', pos.get('side', ''))
                    key = f"{coin}_{side}"
                    details = trade_details.get(key, {})
                    entry_price = float(pos.get('开仓价', pos.get('entry_price', 0)) or 0)
                    size = float(pos.get('数量', pos.get('size', 0)) or 0)
                    stop_loss = details.get('stop_loss', 0)
                    take_profit = details.get('take_profit', 0)
                    
                    # 从CSV获取准确的保证金和杠杆率
                    margin = details.get('margin', 0)
                    leverage = details.get('leverage', 1)
                    
                    # 计算持仓价值 = 保证金 × 杠杆
                    notional_value = margin * leverage
                    
                    # 计算预期盈亏（到止盈价的盈利）
                    expected_pnl = 0
                    if take_profit > 0 and entry_price > 0 and size > 0:
                        if side == '多':
                            expected_pnl = (take_profit - entry_price) * size
                        else:  # 空
                            expected_pnl = (entry_price - take_profit) * size
                    summary['positions'].append({
                        'symbol': coin,
                        'side': side,
                        'size': size,
                        'entry_price': entry_price,
                        'unrealized_pnl': float(pos.get('当前盈亏(U)', pos.get('unrealized_pnl', 0)) or 0),
                        'open_time': utc_to_beijing_time(details.get('open_time', '')),  # UTC→北京时间
                        'stop_loss': stop_loss,
                        'take_profit': take_profit,
                        'risk_reward': details.get('risk_reward', 0),
                        'leverage': leverage,
                        'margin': margin,  # 保证金
                        'notional_value': notional_value,  # 持仓价值
                        'expected_pnl': expected_pnl,
                        'model': model,  # 添加模型字段
                        'open_reason': details.get('open_reason', '')
                    })
                    # 累加总保证金
                    total_margin += margin
        else:
            summary['positions'] = []
        
        # ✅ 重新计算未实现盈亏（从positions统一数据源，确保与持仓列表一致）
        if summary.get('positions'):
            unrealized_pnl_from_positions = sum(
                pos.get('unrealized_pnl', 0) for pos in summary['positions']
            )
            if 'status' in summary:
                summary['status']['unrealized_pnl'] = unrealized_pnl_from_positions
        
        # 重新计算可用余额 = 总资产 - 保证金占用
        if 'status' in summary:
            summary['status']['usdt_balance'] = summary['status']['total_assets'] - total_margin
        
        # 🔥 根据时间周期过滤交易记录（复用前面已读取的all_trades）
        # 已平仓的交易：根据平仓时间筛选
        closed_trades_for_display = [t for t in all_trades if t.get('平仓时间') and t.get('平仓时间').strip()]
        closed_trades_for_display = filter_data_by_time_range(
            closed_trades_for_display, '平仓时间', range_type, start_date, end_date
        )
        
        # 未平仓的交易：根据开仓时间筛选
        open_trades_for_display = [t for t in all_trades if not (t.get('平仓时间') and t.get('平仓时间').strip())]
        open_trades_for_display = filter_data_by_time_range(
            open_trades_for_display, '开仓时间', range_type, start_date, end_date
        )
        
        logging.info(f"[{model}] 显示交易 - 已平仓: {len(closed_trades_for_display)}, 未平仓: {len(open_trades_for_display)}, 时间范围: {range_type}")
        
        # 合并过滤后的交易，并标记来源模型，转换时间为北京时间
        summary['recent_trades'] = []
        for trade in closed_trades_for_display + open_trades_for_display:
            trade['model'] = model  # 标记来源模型
            if trade.get('开仓时间'):
                trade['开仓时间'] = utc_to_beijing_time(trade['开仓时间'])
            if trade.get('平仓时间'):
                trade['平仓时间'] = utc_to_beijing_time(trade['平仓时间'])
            summary['recent_trades'].append(trade)
        
        # 24小时盈亏（适配中英文字段名）
        pnl_file = os.path.join(data_dir, 'pnl_history.csv')
        if os.path.exists(pnl_file):
            with open(pnl_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                # 取最近96条（15分钟一条 = 24小时）
                if len(lines) > 96:
                    lines = [lines[0]] + lines[-96:]
                reader = csv.DictReader(lines)
                pnl_data = list(reader)
                if pnl_data:
                    # 支持中英文字段名
                    start_assets = float(pnl_data[0].get('总资产', pnl_data[0].get('total_assets', 0)))
                    end_assets = float(pnl_data[-1].get('总资产', pnl_data[-1].get('total_assets', 0)))
                    change = end_assets - start_assets
                    change_pct = (change / start_assets * 100) if start_assets > 0 else 0
                    summary['pnl_24h'] = {
                        'start': start_assets,
                        'end': end_assets,
                        'change': change,
                        'change_pct': change_pct
                    }
        
        # 读取当前运行模式（从环境变量文件）
        try:
            # 根据model参数选择对应的环境变量文件
            env_file = '/root/10-23-bot/ds/.env' if model == 'deepseek' else '/root/10-23-bot/ds/.env.qwen'
            if os.path.exists(env_file):
                with open(env_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    # 查找TEST_MODE配置
                    if 'TEST_MODE=True' in content or 'TEST_MODE=true' in content:
                        summary['test_mode'] = True
                    elif 'TEST_MODE=False' in content or 'TEST_MODE=false' in content:
                        summary['test_mode'] = False
                    else:
                        summary['test_mode'] = None
        except:
            summary['test_mode'] = None
        
        # 🆕 读取冷却期状态（从learning_config.json）
        try:
            learning_config_file = os.path.join(data_dir, 'learning_config.json')
            if os.path.exists(learning_config_file):
                with open(learning_config_file, 'r', encoding='utf-8') as f:
                    learning_config = json.load(f)
                    market_regime = learning_config.get('market_regime', {})
                    pause_level = market_regime.get('pause_level', 0)
                    pause_until = market_regime.get('pause_until', None)
                    
                    summary['cooldown_status'] = {
                        'is_paused': pause_level > 0,
                        'pause_level': pause_level,
                        'pause_until': pause_until,
                        'pause_reason': get_pause_reason(pause_level)
                    }
            else:
                summary['cooldown_status'] = {
                    'is_paused': False,
                    'pause_level': 0,
                    'pause_until': None,
                    'pause_reason': ''
                }
        except Exception as e:
            logging.error(f"读取冷却期状态失败: {e}")
            summary['cooldown_status'] = {
                'is_paused': False,
                'pause_level': 0,
                'pause_until': None,
                'pause_reason': ''
            }
        
        return jsonify(summary), 200
    except Exception as e:
        logging.error(f"生成交易摘要失败: {e}")
        import traceback
        logging.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@app.route('/trading-combined', methods=['GET'])
def trading_combined():
    """获取合并后的交易摘要（DeepSeek + 通义千问）"""
    try:
        # 🔥 获取时间周期参数
        range_type = request.args.get('range', 'all')
        start_date = request.args.get('start_date', '')
        end_date = request.args.get('end_date', '')
        
        # 【V8.5.2.4.88优化】记录请求时间，用于分析缓存效果
        request_start = time.time()
        
        # 获取两个模型的数据（传递时间周期参数）
        # 得益于缓存机制，这里不会每次都读取CSV文件
        deepseek_summary = get_model_summary('deepseek', range_type, start_date, end_date)
        qwen_summary = get_model_summary('qwen', range_type, start_date, end_date)
        
        request_duration = int((time.time() - request_start) * 1000)  # 毫秒
        logging.info(f"[/trading-combined] 请求耗时: {request_duration}ms (range={range_type})")
        
        # 计算综合的总资产和总保证金占用
        combined_total_assets = (deepseek_summary.get('status', {}).get('total_assets', 0) + 
                                qwen_summary.get('status', {}).get('total_assets', 0))
        
        # 计算综合的总保证金占用（从positions中累加）
        combined_total_margin = 0
        for pos in deepseek_summary.get('positions', []):
            combined_total_margin += pos.get('margin', 0)
        for pos in qwen_summary.get('positions', []):
            combined_total_margin += pos.get('margin', 0)
        
        # 综合可用余额 = 综合总资产 - 综合保证金占用
        combined_usdt_balance = combined_total_assets - combined_total_margin
        
        combined = {
            'status': {
                'timestamp': deepseek_summary.get('status', {}).get('timestamp', ''),
                # 合并资产数据
                'usdt_balance': combined_usdt_balance,  # 使用计算后的可用余额
                'total_position_value': (deepseek_summary.get('status', {}).get('total_position_value', 0) + 
                    qwen_summary.get('status', {}).get('total_position_value', 0)),
                'unrealized_pnl': 0,  # 🔥 临时值，后续会从合并后的positions重新计算
                'total_assets': combined_total_assets,
                'total_realized_pnl': (deepseek_summary.get('status', {}).get('total_realized_pnl', 0) + 
                    qwen_summary.get('status', {}).get('total_realized_pnl', 0)),
                # 计算合并后的盈利率和年化收益
                'profit_rate': 0,
                'annualized_return': 0,
                'max_drawdown': 0,  # 🔥 最大回撤（稍后计算）
                'sharpe_ratio': 0,  # 🔥 夏普比率（稍后计算）
                'position_count': (deepseek_summary.get('status', {}).get('position_count', 0) + 
                    qwen_summary.get('status', {}).get('position_count', 0)),
                'ai_analysis': '',  # 稍后填充最新一条
                'risk_assessment': '',  # 稍后填充最新一条
                'latest_model': ''  # 新增字段，标识来源
            },
            'experiment_config': {
                'initial_capital': '200U (100U×2)',
                'trading_pairs': ['BTC', 'ETH', 'SOL', 'BNB', 'XRP', 'DOGE', 'LTC'],
                'max_leverage': '≤5x (合约)',
                'strategy': 'AI智能多空策略 + 裸K分析 (双模型)',
                'risk_per_trade': '单模型单笔最大40U'
            },
            'positions': [],  # 先初始化为空，下面填充
            'recent_trades': [],  # 先初始化为空，下面填充
            'pnl_24h': {
                'change': (deepseek_summary.get('pnl_24h', {}).get('change', 0) + 
                    qwen_summary.get('pnl_24h', {}).get('change', 0)),
                'change_pct': 0  # 将在下面计算
            },
            'test_mode': deepseek_summary.get('test_mode'),
            'models': {
                'deepseek': deepseek_summary,
                'qwen': qwen_summary
            }
        }
        
        # 填充positions并添加model标识
        for pos in deepseek_summary.get('positions', []):
            pos['model'] = 'deepseek'
            combined['positions'].append(pos)
        for pos in qwen_summary.get('positions', []):
            pos['model'] = 'qwen'
            combined['positions'].append(pos)
        
        # ✅ 重新计算未实现盈亏（从合并后的positions统一数据源，确保与持仓列表一致）
        if combined.get('positions'):
            unrealized_pnl_from_positions = sum(
                pos.get('unrealized_pnl', 0) for pos in combined['positions']
            )
            combined['status']['unrealized_pnl'] = unrealized_pnl_from_positions
        
        # 填充recent_trades并添加model标识
        all_trades = []
        for trade in deepseek_summary.get('recent_trades', []):
            trade['model'] = 'deepseek'
            all_trades.append(trade)
        for trade in qwen_summary.get('recent_trades', []):
            trade['model'] = 'qwen'
            all_trades.append(trade)
        combined['recent_trades'] = sorted(all_trades, key=lambda x: x.get('平仓时间', ''), reverse=True)
        
        # 获取最新的AI分析（比较时间戳）
        ds_time = deepseek_summary.get('status', {}).get('timestamp', '') if deepseek_summary else ''
        qw_time = qwen_summary.get('status', {}).get('timestamp', '') if qwen_summary else ''
        
        if ds_time and qw_time:
            if ds_time >= qw_time:
                combined['status']['ai_analysis'] = str(deepseek_summary['status'].get('ai_analysis', ''))
                combined['status']['risk_assessment'] = str(deepseek_summary['status'].get('risk_assessment', ''))
                combined['status']['latest_model'] = 'DeepSeek'
            else:
                combined['status']['ai_analysis'] = str(qwen_summary['status'].get('ai_analysis', ''))
                combined['status']['risk_assessment'] = str(qwen_summary['status'].get('risk_assessment', ''))
                combined['status']['latest_model'] = '通义千问'
        elif ds_time:
            combined['status']['ai_analysis'] = str(deepseek_summary['status'].get('ai_analysis', ''))
            combined['status']['risk_assessment'] = str(deepseek_summary['status'].get('risk_assessment', ''))
            combined['status']['latest_model'] = 'DeepSeek'
        elif qw_time:
            combined['status']['ai_analysis'] = str(qwen_summary['status'].get('ai_analysis', ''))
            combined['status']['risk_assessment'] = str(qwen_summary['status'].get('risk_assessment', ''))
            combined['status']['latest_model'] = '通义千问'
        
        # 计算合并后的盈利率（总盈利/总初始资金）
        initial_capital = 200.0  # 两个账户各100U
        total_assets = combined['status']['total_assets']
        if initial_capital > 0:
            combined['status']['profit_rate'] = ((total_assets - initial_capital) / initial_capital * 100)
        
        # 计算年化收益（基于最早的交易时间和合并后的盈利率）
        earliest_time = None
        for model in ['deepseek', 'qwen']:
            model_summary = combined['models'][model]
            all_trades = model_summary.get('recent_trades', [])
            if all_trades:
                for trade in all_trades:
                    open_time_str = trade.get('开仓时间', '')
                    if open_time_str:
                        try:
                            trade_time = datetime.strptime(open_time_str, '%Y-%m-%d %H:%M:%S')
                            if earliest_time is None or trade_time < earliest_time:
                                earliest_time = trade_time
                        except:
                            pass
        
        # 基于最早交易时间计算年化收益（使用复利公式）
        if earliest_time:
            days_elapsed = (datetime.now() - earliest_time).total_seconds() / 86400
            if days_elapsed > 0:
                profit_rate = combined['status']['profit_rate']
                combined['status']['annualized_return'] = ((profit_rate / 100 + 1) ** (365 / days_elapsed) - 1) * 100
            else:
                combined['status']['annualized_return'] = 0
        else:
            combined['status']['annualized_return'] = 0
        
        # 24小时盈亏百分比
        if combined['pnl_24h'].get('change') and total_assets > 0:
            combined['pnl_24h']['change_pct'] = (combined['pnl_24h']['change'] / total_assets * 100)
        
        # 🔥 计算综合的最大回撤和夏普比率
        # 方案1：直接平均两个模型的指标
        ds_max_dd = deepseek_summary.get('status', {}).get('max_drawdown', 0)
        qw_max_dd = qwen_summary.get('status', {}).get('max_drawdown', 0)
        combined['status']['max_drawdown'] = max(ds_max_dd, qw_max_dd)  # 取最大回撤的较大值
        
        ds_sharpe = deepseek_summary.get('status', {}).get('sharpe_ratio', 0)
        qw_sharpe = qwen_summary.get('status', {}).get('sharpe_ratio', 0)
        # 夏普比率取平均值（或加权平均）
        combined['status']['sharpe_ratio'] = (ds_sharpe + qw_sharpe) / 2 if (ds_sharpe or qw_sharpe) else 0
        
        # 🔥 计算综合的胜率
        ds_win_count = deepseek_summary.get('status', {}).get('win_count', 0)
        ds_total_trades = deepseek_summary.get('status', {}).get('total_trades', 0)
        qw_win_count = qwen_summary.get('status', {}).get('win_count', 0)
        qw_total_trades = qwen_summary.get('status', {}).get('total_trades', 0)
        
        combined_win_count = ds_win_count + qw_win_count
        combined_total_trades = ds_total_trades + qw_total_trades
        combined['status']['win_rate'] = (combined_win_count / combined_total_trades * 100) if combined_total_trades > 0 else 0
        combined['status']['win_count'] = combined_win_count
        combined['status']['total_trades'] = combined_total_trades
        
        logging.info(f"[combined] 综合胜率: {combined['status']['win_rate']:.1f}% ({combined_win_count}/{combined_total_trades})")
        
        return jsonify(combined), 200
    except Exception as e:
        logging.error(f"生成合并摘要失败: {e}")
        import traceback
        logging.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

def get_model_summary(model, range_type='all', start_date='', end_date=''):
    """获取单个模型的摘要数据（内部辅助函数）
    :param model: 模型名称（deepseek/qwen）
    :param range_type: 时间范围类型（all/day/week/month/custom）
    :param start_date: 自定义开始日期
    :param end_date: 自定义结束日期
    """
    # 【V8.5.2.4.88优化】缓存逻辑：避免频繁读取CSV导致内存飙升
    cache_key = f"{model}_{range_type}_{start_date}_{end_date}"
    current_time = time.time()
    
    # 检查缓存是否存在且未过期
    if cache_key in SUMMARY_CACHE:
        cached_data, cache_time = SUMMARY_CACHE[cache_key]
        age = int(current_time - cache_time)
        if current_time - cache_time < CACHE_DURATION:
            logging.info(f"[{model}][缓存命中] 使用{age}秒前的数据，跳过CSV读取")
            return cached_data
        else:
            logging.info(f"[{model}][缓存过期] 缓存已过期({age}秒)，重新读取")
    
    try:
        data_dir = get_trading_data_dir(model)
        summary = {}
        
        status_file = os.path.join(data_dir, 'system_status.json')
        trades_file = os.path.join(data_dir, 'trades_history.csv')
        positions_file = os.path.join(data_dir, 'current_positions.csv')
        pnl_file = os.path.join(data_dir, 'pnl_history.csv')
        
        if os.path.exists(status_file):
            with open(status_file, 'r', encoding='utf-8') as f:
                raw_status = json.load(f)
                
                # 读取所有交易记录
                all_trades = []
                if os.path.exists(trades_file):
                    try:
                        with open(trades_file, 'r', encoding='utf-8') as tf:
                            trades_reader = csv.DictReader(tf)
                            trades_reader.fieldnames = [name.strip() if name else name for name in trades_reader.fieldnames]
                            for trade in trades_reader:
                                trade_cleaned = {k.strip() if k else k: v for k, v in trade.items()}
                                all_trades.append(trade_cleaned)
                    except Exception as e:
                        logging.error(f"读取{model}交易历史失败: {e}")
                
                # 🔥 时间周期过滤：过滤已平仓的交易
                closed_trades = [t for t in all_trades if t.get('平仓时间') and t.get('平仓时间').strip()]
                filtered_closed_trades = filter_data_by_time_range(
                    closed_trades, '平仓时间', range_type, start_date, end_date
                )
                
                # 计算总已实现盈亏和胜率（基于过滤后的交易）
                total_realized_pnl = 0
                win_count = 0
                total_count = len(filtered_closed_trades)
                
                for trade in filtered_closed_trades:
                    pnl_str = trade.get('盈亏(U)', '0') or '0'
                    try:
                        pnl = float(pnl_str)
                        total_realized_pnl += pnl
                        if pnl > 0:
                            win_count += 1
                    except (ValueError, TypeError):
                        continue
                
                # 计算胜率
                win_rate = (win_count / total_count * 100) if total_count > 0 else 0
                logging.info(f"[{model}][get_model_summary] 胜率: {win_rate:.1f}% ({win_count}/{total_count})")
                
                # 读取盈亏历史数据（用于计算夏普比率）
                pnl_history = []
                if os.path.exists(pnl_file):
                    try:
                        with open(pnl_file, 'r', encoding='utf-8') as pf:
                            pnl_reader = csv.DictReader(pf)
                            pnl_history = list(pnl_reader)
                            # 根据时间周期过滤盈亏历史
                            pnl_history = filter_data_by_time_range(
                                pnl_history, '时间', range_type, start_date, end_date
                            )
                    except Exception as e:
                        logging.error(f"读取{model}盈亏历史失败: {e}")
                
                # 计算未实现盈亏（当前持仓的盈亏，不受时间筛选影响）
                unrealized_pnl = 0
                if '持仓详情' in raw_status:
                    unrealized_pnl = sum(pos.get('盈亏', 0) for pos in raw_status['持仓详情'])
                
                # 计算指标
                initial_capital = 100.0
                total_assets = raw_status.get('总资产', raw_status.get('total_assets', 0))
                
                # 🔥 根据时间周期计算实际盈利和年化收益
                if range_type == 'all':
                    # 全部数据：使用当前总资产
                    profit_rate = ((total_assets - initial_capital) / initial_capital * 100) if initial_capital > 0 else 0
                else:
                    # 特定周期：基于该周期的已实现盈亏
                    profit_rate = (total_realized_pnl / initial_capital * 100) if initial_capital > 0 else 0
                
                # 计算年化收益率
                annualized_return = 0
                if filtered_closed_trades:
                    # 找到该周期内最早的交易时间
                    try:
                        sorted_trades = sorted(filtered_closed_trades, key=lambda x: x.get('开仓时间', ''))
                        first_trade = sorted_trades[0]
                        start_time = datetime.strptime(first_trade.get('开仓时间', ''), '%Y-%m-%d %H:%M:%S')
                        days_elapsed = (datetime.now() - start_time).total_seconds() / 86400
                        if days_elapsed > 0:
                            annualized_return = ((profit_rate / 100 + 1) ** (365 / days_elapsed) - 1) * 100
                    except Exception as e:
                        logging.error(f"计算年化收益失败: {e}")
                
                # 🔥 计算最大回撤（基于过滤后的交易）
                max_drawdown = calculate_max_drawdown(filtered_closed_trades)
                
                # 🔥 计算夏普比率（基于过滤后的数据）
                sharpe_ratio = calculate_sharpe_ratio(
                    filtered_closed_trades, 
                    pnl_history if pnl_history else None, 
                    initial_capital
                )
                
                # 确保AI分析和风险评估是字符串格式
                ai_analysis = raw_status.get('AI分析', raw_status.get('ai_analysis', ''))
                risk_assessment = raw_status.get('风险评估', raw_status.get('risk_assessment', ''))
                
                # 如果是字典或对象，转换为JSON字符串
                if isinstance(ai_analysis, dict):
                    ai_analysis = json.dumps(ai_analysis, ensure_ascii=False)
                if isinstance(risk_assessment, dict):
                    risk_assessment = json.dumps(risk_assessment, ensure_ascii=False)
                
                summary['status'] = {
                    'timestamp': utc_to_beijing_time(raw_status.get('更新时间', raw_status.get('时间', raw_status.get('timestamp', '')))),  # UTC→北京时间
                    'usdt_balance': 0,  # 先占位，后面会重新计算
                    'total_position_value': raw_status.get('持仓总价值', raw_status.get('总仓位价值', raw_status.get('total_position_value', 0))),
                    'unrealized_pnl': unrealized_pnl,
                    'total_assets': total_assets,
                    'total_realized_pnl': total_realized_pnl,
                    'profit_rate': profit_rate,
                    'annualized_return': annualized_return,
                    'max_drawdown': max_drawdown,  # 🔥 最大回撤
                    'sharpe_ratio': sharpe_ratio,  # 🔥 夏普比率
                    'win_rate': win_rate,  # 🔥 胜率
                    'win_count': win_count,  # 盈利交易数
                    'total_trades': total_count,  # 总交易数
                    'position_count': len(raw_status.get('持仓详情', [])),
                    'ai_analysis': str(ai_analysis) if ai_analysis else '',
                    'risk_assessment': str(risk_assessment) if risk_assessment else ''
                }
        else:
            summary['status'] = {}
        
        # 持仓
        total_margin_model = 0  # 用于计算该模型的总保证金
        if os.path.exists(positions_file):
            with open(positions_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                raw_positions = list(reader)
                
                trade_details = {}
                if os.path.exists(trades_file):
                    with open(trades_file, 'r', encoding='utf-8') as tf:
                        trades_reader = csv.DictReader(tf)
                        for trade in trades_reader:
                            if not trade.get('平仓时间'):
                                key = f"{trade.get('币种', '')}_{trade.get('方向', '')}"
                                trade_details[key] = {
                                    'open_time': trade.get('开仓时间', ''),
                                    'stop_loss': float(trade.get('止损', 0) or 0),
                                    'take_profit': float(trade.get('止盈', 0) or 0),
                                    'risk_reward': float(trade.get('盈亏比', 0) or 0),
                                    'margin': float(trade.get('仓位(U)', 0) or 0),
                                    'leverage': int(trade.get('杠杆率', 1) or 1),
                                    'open_reason': trade.get('开仓理由', '')
                                }
                
                summary['positions'] = []
                for pos in raw_positions:
                    coin = pos.get('币种', pos.get('symbol', ''))
                    side = pos.get('方向', pos.get('side', ''))
                    key = f"{coin}_{side}"
                    details = trade_details.get(key, {})
                    entry_price = float(pos.get('开仓价', pos.get('entry_price', 0)) or 0)
                    size = float(pos.get('数量', pos.get('size', 0)) or 0)
                    stop_loss = details.get('stop_loss', 0)
                    take_profit = details.get('take_profit', 0)
                    
                    # 从CSV获取准确的保证金和杠杆率
                    margin = details.get('margin', 0)
                    leverage = details.get('leverage', 1)
                    
                    # 计算持仓价值 = 保证金 × 杠杆
                    notional_value = margin * leverage
                    
                    # 计算预期盈亏（到止盈价的盈利）
                    expected_pnl = 0
                    if take_profit > 0 and entry_price > 0 and size > 0:
                        if side == '多':
                            expected_pnl = (take_profit - entry_price) * size
                        else:  # 空
                            expected_pnl = (entry_price - take_profit) * size
                    
                    summary['positions'].append({
                        'symbol': coin,
                        'side': side,
                        'size': size,
                        'entry_price': entry_price,
                        'unrealized_pnl': float(pos.get('当前盈亏(U)', pos.get('unrealized_pnl', 0)) or 0),
                        'open_time': utc_to_beijing_time(details.get('open_time', '')),  # UTC→北京时间
                        'stop_loss': stop_loss,
                        'take_profit': take_profit,
                        'risk_reward': details.get('risk_reward', 0),
                        'leverage': leverage,
                        'margin': margin,
                        'notional_value': notional_value,
                        'expected_pnl': expected_pnl,
                        'model': model,  # 标记来源模型
                        'open_reason': details.get('open_reason', '')
                    })
                    # 累加总保证金
                    total_margin_model += margin
        else:
            summary['positions'] = []
        
        # 🔥 根据时间周期筛选持仓（基于开仓时间）
        if summary.get('positions'):
            summary['positions'] = filter_data_by_time_range(
                summary['positions'], 'open_time', range_type, start_date, end_date
            )
        
        # ✅ 重新计算未实现盈亏（从positions统一数据源，确保与持仓列表一致）
        if summary.get('positions'):
            unrealized_pnl_from_positions = sum(
                pos.get('unrealized_pnl', 0) for pos in summary['positions']
            )
            if 'status' in summary:
                summary['status']['unrealized_pnl'] = unrealized_pnl_from_positions
        
        # 重新计算可用余额 = 总资产 - 保证金占用
        if 'status' in summary:
            summary['status']['usdt_balance'] = summary['status']['total_assets'] - total_margin_model
        
        # 所有交易记录（包括未平仓和已平仓）
        if os.path.exists(trades_file):
            with open(trades_file, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                reader.fieldnames = [name.strip() if name else name for name in reader.fieldnames]
                all_trades_raw = []
                for trade in reader:
                    trade_cleaned = {k.strip() if k else k: v for k, v in trade.items()}
                    trade_cleaned['model'] = model  # 标记来源模型
                    all_trades_raw.append(trade_cleaned)
                
                # 🔥 根据时间周期筛选交易记录
                # 已平仓的交易：根据平仓时间筛选
                closed_trades_for_display = [t for t in all_trades_raw if t.get('平仓时间') and t.get('平仓时间').strip()]
                closed_trades_filtered = filter_data_by_time_range(
                    closed_trades_for_display, '平仓时间', range_type, start_date, end_date
                )
                
                # 未平仓的交易：根据开仓时间筛选
                open_trades_for_display = [t for t in all_trades_raw if not (t.get('平仓时间') and t.get('平仓时间').strip())]
                open_trades_filtered = filter_data_by_time_range(
                    open_trades_for_display, '开仓时间', range_type, start_date, end_date
                )
                
                # 合并过滤后的交易，并转换时间为北京时间
                all_filtered_trades = closed_trades_filtered + open_trades_filtered
                for trade in all_filtered_trades:
                    if trade.get('开仓时间'):
                        trade['开仓时间'] = utc_to_beijing_time(trade['开仓时间'])
                    if trade.get('平仓时间'):
                        trade['平仓时间'] = utc_to_beijing_time(trade['平仓时间'])
                summary['recent_trades'] = all_filtered_trades
                logging.info(f"[{model}][get_model_summary] 交易记录 - 已平仓: {len(closed_trades_filtered)}, 未平仓: {len(open_trades_filtered)}")
        else:
            summary['recent_trades'] = []
        
        # 24小时盈亏
        pnl_file = os.path.join(data_dir, 'pnl_history.csv')
        if os.path.exists(pnl_file):
            with open(pnl_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                if len(lines) > 96:
                    lines = [lines[0]] + lines[-96:]
                reader = csv.DictReader(lines)
                pnl_data = list(reader)
                if pnl_data:
                    start_assets = float(pnl_data[0].get('总资产', pnl_data[0].get('total_assets', 0)))
                    end_assets = float(pnl_data[-1].get('总资产', pnl_data[-1].get('total_assets', 0)))
                    change = end_assets - start_assets
                    change_pct = (change / start_assets * 100) if start_assets > 0 else 0
                    summary['pnl_24h'] = {
                        'start': start_assets,
                        'end': end_assets,
                        'change': change,
                        'change_pct': change_pct
                    }
        
        # 读取当前运行模式（从环境变量文件）
        try:
            # 根据model参数选择对应的环境变量文件
            env_file = '/root/10-23-bot/ds/.env' if model == 'deepseek' else '/root/10-23-bot/ds/.env.qwen'
            if os.path.exists(env_file):
                with open(env_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    # 查找TEST_MODE配置
                    if 'TEST_MODE=True' in content or 'TEST_MODE=true' in content:
                        summary['test_mode'] = True
                    elif 'TEST_MODE=False' in content or 'TEST_MODE=false' in content:
                        summary['test_mode'] = False
                    else:
                        summary['test_mode'] = None
            else:
                summary['test_mode'] = None
        except:
            summary['test_mode'] = None
        
        # 🆕 读取冷却期状态（从learning_config.json）
        try:
            learning_config_file = os.path.join(data_dir, 'learning_config.json')
            if os.path.exists(learning_config_file):
                with open(learning_config_file, 'r', encoding='utf-8') as f:
                    learning_config = json.load(f)
                    market_regime = learning_config.get('market_regime', {})
                    pause_level = market_regime.get('pause_level', 0)
                    pause_until = market_regime.get('pause_until', None)
                    
                    summary['cooldown_status'] = {
                        'is_paused': pause_level > 0,
                        'pause_level': pause_level,
                        'pause_until': pause_until,
                        'pause_reason': get_pause_reason(pause_level)
                    }
            else:
                summary['cooldown_status'] = {
                    'is_paused': False,
                    'pause_level': 0,
                    'pause_until': None,
                    'pause_reason': ''
                }
        except Exception as e:
            logging.error(f"读取{model}冷却期状态失败: {e}")
            summary['cooldown_status'] = {
                'is_paused': False,
                'pause_level': 0,
                'pause_until': None,
                'pause_reason': ''
            }
        
        # 🆕 【V8.3.21修复】读取AI决策历史（用于综合页面显示）
        try:
            decisions_file = os.path.join(data_dir, 'ai_decisions.json')
            if os.path.exists(decisions_file):
                with open(decisions_file, 'r', encoding='utf-8') as f:
                    decisions = json.load(f)
                    # 只返回最后10条决策，减少数据传输量
                    if isinstance(decisions, list):
                        summary['ai_decisions'] = decisions[-10:]
                    else:
                        summary['ai_decisions'] = []
            else:
                summary['ai_decisions'] = []
        except Exception as e:
            logging.error(f"读取{model}AI决策历史失败: {e}")
            summary['ai_decisions'] = []
        
        # 【V8.5.2.4.88优化】保存到缓存（30秒有效期）
        SUMMARY_CACHE[cache_key] = (summary, current_time)
        
        # 【V8.5.2.4.88优化】自动清理过期缓存，防止内存泄漏
        expired_keys = [
            k for k, (_, cache_time) in SUMMARY_CACHE.items() 
            if current_time - cache_time > CACHE_DURATION * 3
        ]
        for k in expired_keys:
            del SUMMARY_CACHE[k]
            logging.debug(f"[缓存清理] 删除过期缓存: {k}")
        
        logging.info(f"[{model}][缓存更新] 已保存到缓存，当前缓存数: {len(SUMMARY_CACHE)}")
        
        return summary
    except Exception as e:
        logging.error(f"获取{model}摘要失败: {e}")
        return {}

@app.route('/trading-cache-status', methods=['GET'])
def trading_cache_status():
    """【V8.5.2.4.88优化】查看缓存状态（管理员接口）"""
    try:
        current_time = time.time()
        cache_info = []
        
        for cache_key, (_, cache_time) in SUMMARY_CACHE.items():
            age = int(current_time - cache_time)
            cache_info.append({
                'key': cache_key,
                'age_seconds': age,
                'status': '有效' if age < CACHE_DURATION else '已过期'
            })
        
        return jsonify({
            'cache_count': len(SUMMARY_CACHE),
            'cache_duration': CACHE_DURATION,
            'cache_items': cache_info,
            'memory_tip': '缓存减少了CSV读取次数，降低了内存和CPU占用'
        }), 200
    except Exception as e:
        logging.error(f"获取缓存状态失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/trading-cache-clear', methods=['POST'])
def trading_cache_clear():
    """【V8.5.2.4.88优化】清理缓存（管理员接口）"""
    try:
        cleared_count = len(SUMMARY_CACHE)
        SUMMARY_CACHE.clear()
        logging.info(f"[缓存清理] 手动清理了 {cleared_count} 个缓存项")
        return jsonify({
            'success': True,
            'cleared_count': cleared_count,
            'message': f'已清理 {cleared_count} 个缓存项'
        }), 200
    except Exception as e:
        logging.error(f"清理缓存失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/trading-chat', methods=['POST'])
def trading_chat():
    """与AI对话（需要密码验证）"""
    try:
        data = request.get_json()
        user_message = data.get('message', '').strip()
        password = data.get('password', '').strip()
        model = data.get('model', 'deepseek')  # 支持model参数
        data_dir = get_trading_data_dir(model)
        
        # 密码验证
        if password != CONTROL_PASSWORD:
            return jsonify({'success': False, 'error': '密码错误，无法与AI对话'}), 403
        
        if not user_message:
            return jsonify({'error': '消息不能为空'}), 400
        
        # 调用对应的AI API
        import requests
        
        # 读取系统状态作为上下文
        status_file = os.path.join(data_dir, 'system_status.json')
        context = ""
        if os.path.exists(status_file):
            with open(status_file, 'r', encoding='utf-8') as f:
                status = json.load(f)
                context = f"""
当前系统状态：
- 总资产: {status.get('总资产', status.get('total_assets', 0)):.2f}U
- USDT余额: {status.get('USDT余额', status.get('usdt_balance', 0)):.2f}U
- 持仓数: {status.get('当前持仓数', status.get('position_count', 0))}
- AI分析: {status.get('AI分析', status.get('ai_analysis', '无'))}
"""
        
        # 根据model选择API
        if model == 'qwen':
            api_key = os.getenv('QWEN_API_KEY', '')
            api_url = 'https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions'
            ai_model = 'qwen-turbo'
        else:  # deepseek
            api_key = os.getenv('DEEPSEEK_API_KEY', 'sk-1d8568a372774640ad4daac128ede404')
            api_url = 'https://api.deepseek.com/chat/completions'
            ai_model = 'deepseek-chat'
        
        response = requests.post(
            api_url,
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json'
            },
            json={
                'model': ai_model,
                'messages': [
                    {'role': 'system', 'content': f'你是一个专业的加密货币交易顾问。{context}'},
                    {'role': 'user', 'content': user_message}
                ],
                'temperature': 0.7
            },
            timeout=30
        )
        
        if response.status_code == 200:
            ai_reply = response.json()['choices'][0]['message']['content']
            beijing_tz = pytz.timezone('Asia/Shanghai')
            beijing_time = datetime.now(beijing_tz).strftime('%Y-%m-%d %H:%M:%S')
            return jsonify({
                'success': True,
                'reply': ai_reply,
                'timestamp': beijing_time
            }), 200
        else:
            return jsonify({
                'success': False,
                'error': f'AI API错误: {response.status_code}'
            }), 500
            
    except Exception as e:
        logging.error(f"AI对话失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/debug-status-check', methods=['GET'])
def debug_status_check():
    """调试AI状态检测"""
    import time
    model = request.args.get('model', 'deepseek')
    data_dir = get_trading_data_dir(model)
    status_file = os.path.join(data_dir, 'system_status.json')
    
    result = {
        'TRADING_DATA_BASE': TRADING_DATA_BASE,
        'model': model,
        'data_dir': data_dir,
        'status_file': status_file,
        'file_exists': os.path.exists(status_file),
    }
    
    if os.path.exists(status_file):
        try:
            file_mtime = os.path.getmtime(status_file)
            last_update = datetime.fromtimestamp(file_mtime).strftime('%Y-%m-%d %H:%M:%S')
            time_diff = time.time() - file_mtime
            is_active = time_diff < 1800
            result.update({
                'last_update': last_update,
                'time_diff_seconds': time_diff,
                'is_active': is_active,
                'threshold': 1800
            })
        except Exception as e:
            result['error'] = str(e)
    
    return jsonify(result), 200

@app.route('/trading-ai-status', methods=['GET'])
def trading_ai_status():
    """获取AI进程的真实运行状态"""
    import time  # ← 添加time导入！
    try:
        model = request.args.get('model', 'deepseek')
        data_dir = get_trading_data_dir(model)
        
        # 根据模型选择进程名
        if model == 'qwen':
            process_name = 'qwen_多币种智能版.py'
            screen_name = 'ai-qwen'
        else:
            process_name = 'deepseek_多币种智能版.py'
            screen_name = 'ai-deepseek'
        
        # 1. 检查进程是否在运行
        is_running = False
        try:
            import subprocess
            result = subprocess.run(['pgrep', '-f', process_name], capture_output=True, text=True, timeout=5)
            is_running = len(result.stdout.strip()) > 0
        except:
            pass
        
        # 2. 检查最近更新时间（判断是否僵死）
        status_file = os.path.join(data_dir, 'system_status.json')
        is_active = False
        last_update = None
        logging.info(f"[AI Status] Checking status_file: {status_file}, exists: {os.path.exists(status_file)}")
        if os.path.exists(status_file):
            try:
                file_mtime = os.path.getmtime(status_file)
                last_update = datetime.fromtimestamp(file_mtime).strftime('%Y-%m-%d %H:%M:%S')
                time_diff = time.time() - file_mtime
                # 如果文件在30分钟内更新过，认为是活跃的
                is_active = time_diff < 1800
                logging.info(f"[AI Status] {model}: time_diff={time_diff:.0f}s, is_active={is_active}")
            except Exception as e:
                logging.error(f"[AI Status] Error reading status file: {e}")
                pass
        
        # 3. 检查冷却期状态
        is_paused = False
        pause_reason = ''
        pause_until = None
        try:
            learning_config_file = os.path.join(data_dir, 'learning_config.json')
            if os.path.exists(learning_config_file):
                with open(learning_config_file, 'r', encoding='utf-8') as f:
                    learning_config = json.load(f)
                    market_regime = learning_config.get('market_regime', {})
                    pause_level = market_regime.get('pause_level', 0)
                    pause_until = market_regime.get('pause_until', None)
                    is_paused = pause_level > 0
                    pause_reason = get_pause_reason(pause_level)
        except:
            pass
        
        # 4. 检查运行模式
        test_mode = None
        try:
            env_file = '/root/10-23-bot/ds/.env' if model == 'deepseek' else '/root/10-23-bot/ds/.env.qwen'
            if os.path.exists(env_file):
                with open(env_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if 'TEST_MODE=True' in content or 'TEST_MODE=true' in content:
                        test_mode = True
                    elif 'TEST_MODE=False' in content or 'TEST_MODE=false' in content:
                        test_mode = False
        except:
            pass
        
        # 综合判断状态
        if not is_running:
            status = 'offline'
            status_text = '离线'
            status_emoji = '⚫'
        elif is_paused:
            status = 'cooldown'
            status_text = '冷却中'
            status_emoji = '❄️'
        elif is_running and is_active:
            status = 'online'
            status_text = '在线'
            status_emoji = '🟢'
        elif is_running and not is_active:
            status = 'stale'
            status_text = '异常'
            status_emoji = '🟡'
        else:
            status = 'unknown'
            status_text = '未知'
            status_emoji = '⚪'
        
        return jsonify({
            'status': status,
            'status_text': status_text,
            'status_emoji': status_emoji,
            'is_running': is_running,
            'is_active': is_active,
            'is_paused': is_paused,
            'pause_reason': pause_reason,
            'pause_until': pause_until,
            'test_mode': test_mode,
            'last_update': last_update,
            'model': model
        }), 200
        
    except Exception as e:
        logging.error(f"获取AI状态失败: {e}")
        return jsonify({
            'error': str(e), 
            'status': 'error', 
            'status_text': '获取失败',
            'status_emoji': '❌'
        }), 500

@app.route('/trading-control', methods=['POST'])
def trading_control():
    """控制交易系统（切换模式/重启/停止）"""
    try:
        data = request.get_json()
        action = data.get('action')  # 'toggle_mode', 'restart', 'stop'
        password = data.get('password')  # 安全验证
        model = data.get('model', 'deepseek')  # 支持指定模型
        
        if password != CONTROL_PASSWORD:
            return jsonify({'error': '密码错误'}), 403
        
        # 根据model选择环境变量文件和bot脚本
        if model == 'qwen':
            env_file = '/home/admin/10-23-bot/ds/.env.qwen'
            bot_script = 'qwen_多币种智能版.py'
            screen_name = 'ai-qwen'
            model_name = '通义千问'
        else:
            env_file = '/home/admin/10-23-bot/ds/.env'
            bot_script = 'deepseek_多币种智能版.py'
            screen_name = 'ai-deepseek'
            model_name = 'DeepSeek'
        
        if action == 'toggle_mode':
            # 切换测试/实盘模式
            if not os.path.exists(env_file):
                return jsonify({'error': f'{model_name}环境变量文件不存在'}), 404
            
            # 读取环境变量文件
            with open(env_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 切换TEST_MODE
            if 'TEST_MODE=True' in content or 'TEST_MODE=true' in content:
                new_content = content.replace('TEST_MODE=True', 'TEST_MODE=False').replace('TEST_MODE=true', 'TEST_MODE=False')
                new_mode = 'LIVE'
            elif 'TEST_MODE=False' in content or 'TEST_MODE=false' in content:
                new_content = content.replace('TEST_MODE=False', 'TEST_MODE=True').replace('TEST_MODE=false', 'TEST_MODE=True')
                new_mode = 'TEST'
            else:
                # 如果没有TEST_MODE配置，添加为False（实盘）
                new_content = content + '\nTEST_MODE=False\n'
                new_mode = 'LIVE'
            
            # 写回环境变量文件
            with open(env_file, 'w', encoding='utf-8') as f:
                f.write(new_content)
            
            # 自动重启对应的bot
            import subprocess
            try:
                # 停止旧进程
                subprocess.run(['pkill', '-9', '-f', bot_script], timeout=5)
                import time
                time.sleep(2)
                
                # 启动新进程
                start_cmd = f"cd /home/admin/10-23-bot/ds && set -a; source {env_file}; set +a; exec /home/admin/10-23-bot/ds/venv/bin/python -u {bot_script} 2>&1 | tee -a logs/{model}_trading.log"
                subprocess.Popen(['screen', '-dmS', screen_name, 'bash', '-c', start_cmd])
                time.sleep(3)
                
                # 检查是否启动成功
                check_result = subprocess.run(['ps', 'aux'], capture_output=True, text=True, timeout=5)
                is_running = bot_script in check_result.stdout
                
                return jsonify({
                    'message': f'{model_name}模式已切换为: {new_mode}',
                    'new_mode': new_mode,
                    'model': model_name,
                    'restarted': is_running,
                    'note': '已自动重启交易系统' if is_running else '切换成功但重启失败，请手动重启'
                }), 200
            except Exception as e:
                return jsonify({
                    'message': f'{model_name}模式已切换为: {new_mode}',
                    'new_mode': new_mode,
                    'model': model_name,
                    'error': f'自动重启失败: {str(e)}',
                    'note': '请手动重启交易系统'
            }), 200
        
        elif action == 'get_status':
            # 获取系统运行状态
            import subprocess
            try:
                result = subprocess.run(
                    ['screen', '-ls'],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                is_running = screen_name in result.stdout
                
                # 读取当前模式（从环境变量文件）
                current_mode = 'UNKNOWN'
                if os.path.exists(env_file):
                    with open(env_file, 'r', encoding='utf-8') as f:
                        content = f.read()
                        if 'TEST_MODE=True' in content or 'TEST_MODE=true' in content:
                            current_mode = 'TEST'
                        elif 'TEST_MODE=False' in content or 'TEST_MODE=false' in content:
                            current_mode = 'LIVE'
                
                return jsonify({
                    'running': is_running,
                    'mode': current_mode,
                    'model': model_name,
                    'screen_output': result.stdout
                }), 200
            except Exception as e:
                return jsonify({'error': f'检查状态失败: {str(e)}'}), 500
        
        else:
            return jsonify({'error': '未知操作'}), 400
        
    except Exception as e:
        logging.error(f"控制交易系统失败: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/trading-price-data', methods=['GET'])
def trading_price_data():
    """获取代币价格K线数据 - 使用csv模块，无需pandas"""
    try:
        model = request.args.get('model', 'deepseek')
        symbol = request.args.get('symbol', 'BTC')
        range_type = request.args.get('range', 'day')
        start_date_str = request.args.get('start_date', '')
        end_date_str = request.args.get('end_date', '')
        
        # 计算北京时间范围，然后转换为UTC用于过滤
        from datetime import timezone
        beijing_tz = timezone(timedelta(hours=8))
        now_beijing = datetime.now(beijing_tz).replace(tzinfo=None)
        
        if range_type == 'day':
            start_beijing = now_beijing.replace(hour=0, minute=0, second=0, microsecond=0)
            end_beijing = now_beijing
        elif range_type == 'week':
            days_since_monday = now_beijing.weekday()
            start_beijing = (now_beijing - timedelta(days=days_since_monday)).replace(hour=0, minute=0, second=0, microsecond=0)
            end_beijing = now_beijing
        elif range_type == 'month':
            start_beijing = now_beijing.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            end_beijing = now_beijing
        elif range_type == 'custom' and start_date_str and end_date_str:
            start_beijing = datetime.strptime(start_date_str, '%Y-%m-%d')
            end_beijing = datetime.strptime(end_date_str, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
        else:  # all - 改为365天以覆盖所有历史数据
            start_beijing = now_beijing - timedelta(days=365)
            end_beijing = now_beijing
        
        # 转换为UTC时间用于过滤CSV数据（CSV中存储的是UTC时间）
        start_dt = start_beijing - timedelta(hours=8)
        end_dt = end_beijing - timedelta(hours=8)
        
        logging.info(f"[价格数据] 北京时间范围: {start_beijing} ~ {end_beijing}")
        logging.info(f"[价格数据] UTC时间范围: {start_dt} ~ {end_dt}")
        
        def get_model_kline_data(model_name):
            """获取单个模型的K线数据"""
            data_dir = os.path.join(TRADING_DATA_BASE, model_name)
            kline_data = []
            
            # 遍历日期读取market_snapshots - 使用日期循环而不是日期时间
            current_date = start_dt.date()
            end_date = end_dt.date()
            while current_date <= end_date:
                date_str = current_date.strftime('%Y%m%d')
                snapshot_file = os.path.join(data_dir, 'market_snapshots', f'{date_str}.csv')
                
                if os.path.exists(snapshot_file):
                    try:
                        with open(snapshot_file, 'r', encoding='utf-8-sig') as f:
                            reader = csv.DictReader(f)
                            for row in reader:
                                if row.get('coin', '').upper() == symbol.upper():
                                    time_str = row.get('time', '').strip()
                                    # 规范化时间格式：0000 -> 00:00:00
                                    if time_str and len(time_str) == 4 and time_str.isdigit():
                                        time_str = f"{time_str[:2]}:{time_str[2:]}:00"
                                    elif ':' in time_str and len(time_str.split(':')) == 2:
                                        time_str = time_str + ":00"
                                    
                                    # UTC时间 - 使用当前日期构造完整时间戳
                                    timestamp_utc = f"{current_date.strftime('%Y-%m-%d')} {time_str}"
                                    try:
                                        # 转换为北京时间
                                        timestamp_bj = utc_to_beijing_time(timestamp_utc)
                                        beijing_dt = datetime.strptime(timestamp_bj, '%Y-%m-%d %H:%M:%S')
                                        
                                        # 按北京时间范围过滤
                                        if start_beijing <= beijing_dt <= end_beijing:
                                            # 验证并转换价格数据
                                            try:
                                                open_price = float(row.get('open', 0) or 0)
                                                high_price = float(row.get('high', 0) or 0)
                                                low_price = float(row.get('low', 0) or 0)
                                                close_price = float(row.get('close', 0) or 0)
                                                # 过滤无效数据（0或负数）
                                                if all([open_price > 0, high_price > 0, low_price > 0, close_price > 0]):
                                                    kline_data.append({
                                                        'timestamp': timestamp_bj,
                                                        'open': open_price,
                                                        'high': high_price,
                                                        'low': low_price,
                                                        'close': close_price
                                                    })
                                            except (ValueError, TypeError) as e:
                                                logging.warning(f"无效K线数据: {timestamp_utc}, 错误: {e}")
                                    except Exception as e:
                                        logging.error(f"K线时间转换失败: {timestamp_utc}, 错误: {e}")
                    except Exception as e:
                        logging.error(f"读取快照文件失败 {snapshot_file}: {e}")
                
                current_date += timedelta(days=1)
            
            logging.info(f"[K线数据] {model_name} {symbol}: 共{len(kline_data)}条")
            if kline_data:
                logging.info(f"[K线数据] 时间范围: {kline_data[0]['timestamp']} ~ {kline_data[-1]['timestamp']}")
            return kline_data
        
        def get_model_trade_markers(model_name):
            """获取单个模型的交易标注"""
            data_dir = os.path.join(TRADING_DATA_BASE, model_name)
            trades_file = os.path.join(data_dir, 'trades_history.csv')
            trade_markers = []
            total_trades = 0
            matched_trades = 0
            
            logging.info(f"[订单标注] 读取文件: {trades_file}")
            
            if os.path.exists(trades_file):
                try:
                    with open(trades_file, 'r', encoding='utf-8-sig') as f:
                        reader = csv.DictReader(f)
                        for trade in reader:
                            coin = trade.get('币种', '').split('/')[0].upper()
                            if coin != symbol.upper():
                                continue
                            
                            total_trades += 1
                            
                            # 开仓标注
                            open_time = trade.get('开仓时间', '')
                            if open_time:
                                try:
                                    open_dt = datetime.strptime(open_time, '%Y-%m-%d %H:%M:%S')
                                    logging.info(f"[订单标注] 检查开仓: {open_time} (UTC), 范围: {start_dt} ~ {end_dt}")
                                    if start_dt <= open_dt <= end_dt:
                                        # UTC转北京时间
                                        open_time_bj = utc_to_beijing_time(open_time)
                                        trade_markers.append({
                                            'type': 'open',
                                            'timestamp': open_time_bj,
                                            'price': float(trade.get('开仓价格', 0) or 0),
                                            'side': trade.get('方向', ''),
                                            'reason': trade.get('开仓理由', ''),
                                            'size': float(trade.get('仓位(U)', 0) or 0),
                                            'model': model_name
                                        })
                                        matched_trades += 1
                                        logging.info(f"[订单标注] ✅ 开仓匹配: {open_time} -> {open_time_bj}")
                                    else:
                                        logging.info(f"[订单标注] ❌ 开仓超出范围: {open_time}")
                                except Exception as e:
                                    logging.error(f"[订单标注] 开仓时间解析失败: {open_time}, 错误: {e}")
                            
                            # 平仓标注
                            close_time = trade.get('平仓时间', '')
                            if close_time and close_time.strip():
                                try:
                                    close_dt = datetime.strptime(close_time, '%Y-%m-%d %H:%M:%S')
                                    logging.info(f"[订单标注] 检查平仓: {close_time} (UTC), 范围: {start_dt} ~ {end_dt}")
                                    if start_dt <= close_dt <= end_dt:
                                        # UTC转北京时间
                                        close_time_bj = utc_to_beijing_time(close_time)
                                        # 计算持仓时间
                                        hold_time_str = ''
                                        if open_time:
                                            try:
                                                open_dt_obj = datetime.strptime(open_time, '%Y-%m-%d %H:%M:%S')
                                                close_dt_obj = datetime.strptime(close_time, '%Y-%m-%d %H:%M:%S')
                                                hold_duration = close_dt_obj - open_dt_obj
                                                days = hold_duration.days
                                                hours = hold_duration.seconds // 3600
                                                minutes = (hold_duration.seconds % 3600) // 60
                                                if days > 0:
                                                    hold_time_str = f"{days}天{hours}小时"
                                                elif hours > 0:
                                                    hold_time_str = f"{hours}小时{minutes}分钟"
                                                else:
                                                    hold_time_str = f"{minutes}分钟"
                                            except:
                                                hold_time_str = ''
                                        trade_markers.append({
                                            'type': 'close',
                                            'timestamp': close_time_bj,
                                            'price': float(trade.get('平仓价格', 0) or 0),
                                            'open_price': float(trade.get('开仓价格', 0) or 0),
                                            'pnl': float(trade.get('盈亏(U)', 0) or 0),
                                            'hold_time': hold_time_str,
                                            'reason': trade.get('平仓理由', ''),
                                            'model': model_name
                                        })
                                        matched_trades += 1
                                        logging.info(f"[订单标注] ✅ 平仓匹配: {close_time} -> {close_time_bj}")
                                    else:
                                        logging.info(f"[订单标注] ❌ 平仓超出范围: {close_time}")
                                except Exception as e:
                                    logging.error(f"[订单标注] 平仓时间解析失败: {close_time}, 错误: {e}")
                except Exception as e:
                    logging.error(f"读取交易文件失败 {trades_file}: {e}")
            else:
                logging.warning(f"[订单标注] 文件不存在: {trades_file}")
            
            logging.info(f"[订单标注] {model_name} 总交易数: {total_trades}, 匹配数: {matched_trades}, 标注数: {len(trade_markers)}")
            return trade_markers
        
        # 获取K线数据和交易标注
        if model == 'combined':
            ds_kline = get_model_kline_data('deepseek')
            qw_kline = get_model_kline_data('qwen')
            # 合并并按时间排序
            kline_dict = {}
            for k in ds_kline + qw_kline:
                ts = k['timestamp']
                if ts not in kline_dict:
                    kline_dict[ts] = k
                else:
                    # 取平均值
                    kline_dict[ts]['close'] = (kline_dict[ts]['close'] + k['close']) / 2
            kline_data = sorted(kline_dict.values(), key=lambda x: x['timestamp'])
            
            # 合并交易标注
            ds_markers = get_model_trade_markers('deepseek')
            qw_markers = get_model_trade_markers('qwen')
            trade_markers = ds_markers + qw_markers
        else:
            kline_data = get_model_kline_data(model)
            trade_markers = get_model_trade_markers(model)
        
        # 计算代币统计
        close_trades = [m for m in trade_markers if m['type'] == 'close']
        total_pnl = sum(m.get('pnl', 0) for m in close_trades)
        win_count = sum(1 for m in close_trades if m.get('pnl', 0) > 0)
        trade_count = len(close_trades)
        win_rate = (win_count / trade_count * 100) if trade_count > 0 else 0
        
        symbol_stats = {
            'total_pnl': round(total_pnl, 2),
            'win_rate': round(win_rate, 1),
            'trade_count': trade_count
        }
        
        # 添加日志显示返回给前端的K线时间范围
        if kline_data and len(kline_data) > 0:
            first_time = kline_data[0]['timestamp']
            last_time = kline_data[-1]['timestamp']
            logging.info(f"[价格数据] ✅ 返回K线{len(kline_data)}条: {first_time} ~ {last_time}")
        else:
            logging.info(f"[价格数据] ⚠️ 无K线数据")
        
        logging.info(f"[价格数据] 订单标注{len(trade_markers)}个, 总盈亏{total_pnl:.2f}U")
        
        return jsonify({
            'symbol': symbol,
            'kline_data': kline_data,
            'trade_markers': sorted(trade_markers, key=lambda x: x['timestamp']),
            'symbol_stats': symbol_stats
        }), 200
        
    except Exception as e:
        logging.error(f"获取价格数据失败: {e}")
        import traceback
        logging.error(traceback.format_exc())
        return jsonify({'error': str(e)}), 500


@app.route('/')
@app.route('/trading-dashboard')
def trading_dashboard():
    """AI交易系统完整监控页面"""
    log_visitor()  # 记录访客
    return '''<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>追踪狗AI交易系统（内测版）</title><meta name="description" content="追踪狗AI交易系统 - 基于DeepSeek和通义千问的智能交易监控平台"><meta name="theme-color" content="#f0bc3b"><meta name="apple-mobile-web-app-capable" content="yes"><meta name="apple-mobile-web-app-status-bar-style" content="black-translucent"><meta name="apple-mobile-web-app-title" content="追踪狗AI"><link rel="icon" type="image/png" href="https://bitechain.io/assets/images/logo/soltracker-logo.png"/><link rel="apple-touch-icon" href="https://bitechain.io/assets/images/logo/soltracker-logo.png"><link rel="apple-touch-icon" sizes="152x152" href="https://bitechain.io/assets/images/logo/soltracker-logo.png"><link rel="apple-touch-icon" sizes="180x180" href="https://bitechain.io/assets/images/logo/soltracker-logo.png"><link rel="apple-touch-icon" sizes="167x167" href="https://bitechain.io/assets/images/logo/soltracker-logo.png"><script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script><script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-zoom@2.0.1/dist/chartjs-plugin-zoom.min.js"></script><script src="https://unpkg.com/lightweight-charts@4.1.0/dist/lightweight-charts.standalone.production.js"></script><style>*{margin:0;padding:0;box-sizing:border-box}body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC',sans-serif;background:#fef8ed;padding:20px}.think-content{padding:10px;font-size:11px;color:#555;white-space:pre-wrap;height:150px;overflow-y:auto;line-height:1.5;display:none;background:#fff;border-radius:4px}@media(max-width:768px){body{padding:10px}}.container{max-width:1600px;margin:0 auto}.header{background:linear-gradient(135deg,#f0bc3b 0%,#e8a825 100%);color:#2d1b00;padding:25px 30px;border-radius:12px;margin-bottom:20px;box-shadow:0 4px 20px rgba(240,188,59,0.3);display:flex;align-items:center;gap:15px}.logo{width:50px;height:50px;border-radius:50%;background:white;padding:5px;box-shadow:0 2px 8px rgba(0,0,0,0.1)}.logo img{width:100%;height:100%;object-fit:contain}.header-content{flex:1}.header h1{margin-bottom:8px;font-size:26px;font-weight:700}.header-subtitle{font-size:12px;opacity:0.85}.header-actions{display:flex;align-items:center;gap:8px;margin-top:8px;flex-wrap:wrap}.header-right{display:flex;align-items:center;gap:10px;flex-direction:column}.visitor-count{display:inline-flex;align-items:center;gap:5px;padding:6px 12px;background:#f0bc3b;border:2px solid #f0bc3b;border-radius:6px;font-size:12px;font-weight:700;white-space:nowrap;color:#2d1b00;box-shadow:0 2px 8px rgba(240,188,59,0.3)}.share-btn{display:inline-flex;align-items:center;gap:5px;padding:8px 16px;background:#f0bc3b;border:2px solid #f0bc3b;color:#2d1b00;border-radius:6px;cursor:pointer;font-size:12px;font-weight:700;transition:all 0.3s;white-space:nowrap;box-shadow:0 2px 8px rgba(240,188,59,0.3)}.share-btn:hover{transform:translateY(-1px);box-shadow:0 4px 12px rgba(240,188,59,0.4)}.performance-badge{display:inline-block;padding:8px 16px;background:rgba(255,255,255,0.3);border-radius:8px;margin-left:8px;font-size:13px;font-weight:700;border:2px solid rgba(255,255,255,0.5)}.performance-badge.positive{background:rgba(16,185,129,0.2);border-color:#10b981;color:#065f46}.performance-badge.negative{background:rgba(239,68,68,0.2);border-color:#ef4444;color:#991b1b}.performance-badge.neutral{background:rgba(59,130,246,0.2);border-color:#3b82f6;color:#1e3a8a}.experiment-info{background:rgba(255,255,255,0.2);padding:12px 20px;border-radius:8px;margin-top:12px;font-size:12px;display:flex;flex-wrap:nowrap;gap:15px;border:1px solid rgba(255,255,255,0.3);justify-content:space-between;width:100%}.experiment-info-item{display:flex;align-items:center;gap:5px}.experiment-info-item strong{font-weight:600}.control-btn{padding:8px 16px;background:#f0bc3b;border:2px solid #f0bc3b;color:#2d1b00;border-radius:6px;cursor:pointer;margin-left:10px;font-size:13px;font-weight:700;transition:all 0.3s;box-shadow:0 2px 8px rgba(240,188,59,0.3)}.control-btn:hover{transform:translateY(-1px);box-shadow:0 4px 12px rgba(240,188,59,0.4)}.stats-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:15px;margin-bottom:20px}.stat-box{background:linear-gradient(135deg,#f0bc3b 0%,#e8a825 100%);color:#2d1b00;padding:20px;border-radius:10px;box-shadow:0 2px 10px rgba(240,188,59,0.2)}.stat-label{font-size:13px;opacity:0.9;margin-bottom:8px}.stat-value{font-size:28px;font-weight:bold}.grid{display:grid;grid-template-columns:2fr 1fr;gap:20px;align-items:start}.grid>div{display:flex;flex-direction:column}.grid>div:last-child>div:first-child{flex:1 1 auto;display:flex;flex-direction:column}.grid>div:last-child>div:last-child{flex:0 0 auto}@media(max-width:1200px){.grid{grid-template-columns:1fr}}.card{background:white;border-radius:10px;padding:25px;box-shadow:0 2px 10px rgba(0,0,0,0.1);margin-bottom:20px;overflow:visible;position:relative}.card-title{font-size:18px;font-weight:600;margin-bottom:15px;color:#333}.chart-container{position:relative;height:450px;margin-top:20px;padding-top:20px;overflow:visible;z-index:10}.chart-controls{display:flex;gap:8px;margin-bottom:15px;flex-wrap:wrap;align-items:center}.time-range-btn{padding:6px 12px;border:1px solid #e2e8f0;background:white;border-radius:6px;cursor:pointer;font-size:12px;color:#64748b;transition:all 0.3s}.time-range-btn:hover{background:#f8fafc;border-color:#f0bc3b}.time-range-btn.active{background:#f0bc3b;color:#2d1b00;border-color:#f0bc3b;font-weight:600}.symbol-btn{padding:6px 14px;border:1px solid #e2e8f0;background:white;border-radius:6px;cursor:pointer;font-size:12px;color:#64748b;transition:all 0.3s;font-weight:600}.symbol-btn:hover{background:#f8fafc;border-color:#f0bc3b}.symbol-btn.active{background:#f0bc3b;color:#2d1b00;border-color:#f0bc3b}.date-picker-group{display:flex;gap:6px;align-items:center}.date-picker-input{padding:6px 10px;border:1px solid #e2e8f0;border-radius:6px;font-size:12px;color:#64748b;cursor:pointer}table{width:100%;border-collapse:collapse}thead{background:#f8fafc}th,td{padding:12px;text-align:left;border-bottom:1px solid #e2e8f0;font-size:13px}th{font-weight:600;color:#475569}td{color:#334155}.profit{color:#10b981;font-weight:600}.loss{color:#ef4444;font-weight:600}.loading,.no-data{text-align:center;padding:30px;color:#999;font-size:14px}.unified-btn{display:inline-flex;align-items:center;justify-content:center;gap:5px;padding:6px 12px;background:#f0bc3b;border:2px solid #f0bc3b;border-radius:6px;color:#2d1b00;font-size:13px;font-weight:700;cursor:pointer;transition:all 0.3s;white-space:nowrap;box-shadow:0 2px 8px rgba(240,188,59,0.3);text-decoration:none}.unified-btn:hover{transform:translateY(-1px);box-shadow:0 4px 12px rgba(240,188,59,0.4)}.unified-btn.active{border:3px solid #f97316;padding:5px 11px}.unified-btn.paused{animation:pulse 2s infinite}@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.7}}.button-row-top{display:flex;gap:10px;margin-top:12px;justify-content:flex-start;flex-wrap:wrap}.button-row-bottom{display:flex;gap:10px;margin-top:10px;justify-content:center;flex-wrap:wrap}.mobile-buttons{display:none}.mobile-btn-row{display:flex;gap:8px;margin-top:8px;justify-content:center;align-items:center;flex-wrap:wrap;width:100%}.mobile-btn{display:inline-flex;align-items:center;justify-content:center;gap:5px;padding:8px 12px;background:#f0bc3b;border:2px solid #f0bc3b;border-radius:6px;color:#2d1b00;font-size:11px;font-weight:700;cursor:pointer;transition:all 0.3s;white-space:nowrap;box-shadow:0 2px 8px rgba(240,188,59,0.3);text-decoration:none;box-sizing:border-box}.mobile-btn:hover{transform:translateY(-1px);box-shadow:0 4px 12px rgba(240,188,59,0.4)}.mobile-btn.active{border:3px solid #f97316;padding:7px 11px}.mode-badge{display:inline-block;padding:6px 12px;border-radius:6px;font-size:13px;font-weight:600;margin-left:10px}.mode-test{background:#fef3c7;color:#92400e}.mode-live{background:#fee2e2;color:#991b1b}.cooldown-badge{display:inline-block;padding:6px 12px;border-radius:6px;font-size:13px;font-weight:600;margin-left:10px;animation:pulse 2s infinite}.cooldown-normal{background:#d1fae5;color:#065f46;border:2px solid #10b981}.cooldown-paused{background:#fee2e2;color:#991b1b;border:2px solid #ef4444}.cooldown-badge.cooldown-normal{animation:none}.chat-container{min-height:400px;max-height:800px;display:flex;flex-direction:column}.chat-messages{flex:1;overflow-y:auto;padding:15px;background:#f8fafc;border-radius:8px;margin-bottom:15px;min-height:300px}.message{margin-bottom:15px}.message-user{text-align:right}.message-ai-decision{background:#f0f9ff;padding:12px;border-left:3px solid #0ea5e9;border-radius:6px;margin-bottom:15px}.message-ai-decision.executed{background:linear-gradient(135deg,#fff9e6 0%,#ffffff 100%);border-left:4px solid #f0bc3b;box-shadow:0 2px 8px rgba(240,188,59,0.15)}.message-ai-decision.executed::before{content:'✓ 实际执行';display:inline-block;padding:4px 10px;background:#f0bc3b;color:#2d1b00;border-radius:4px;font-size:11px;font-weight:700;margin-bottom:8px}.decision-content{color:#1e293b;line-height:1.6;background:transparent !important}.decision-analysis{font-size:13px;margin-bottom:15px;padding-bottom:12px;border-bottom:1px solid #e2e8f0;background:transparent !important;line-height:1.8}.decision-risk{font-size:12px;color:#475569;background:transparent !important;padding-top:5px;line-height:1.8}.message-ai-decision .decision-content,.message-ai-decision .decision-analysis,.message-ai-decision .decision-risk{background:transparent !important}.think-box{background:transparent;border:none;border-radius:6px;margin-bottom:12px;overflow:visible}.think-toggle{display:flex;align-items:center;justify-content:space-between;padding:8px 10px;cursor:pointer;background:#f8fafc;border-bottom:1px solid #e2e8f0;user-select:none}.think-toggle:hover{background:#f0f9ff}.think-title{font-size:12px;font-weight:600;color:#0ea5e9}.think-arrow{font-size:10px;color:#666;transition:transform 0.2s}.think-arrow.open{transform:rotate(180deg)}.think-content.show{display:block}.message-content{display:inline-block;max-width:80%;padding:10px 14px;border-radius:10px;word-wrap:break-word;font-size:14px;line-height:1.6}.message-user .message-content{background:linear-gradient(135deg,#667eea 0%,#764ba2 100%);color:white}.message-ai .message-content{background:white;border:1px solid #e2e8f0;color:#333}.message-time{font-size:11px;color:#999;margin-top:5px}.chat-input-area{display:flex;gap:10px}.chat-input{flex:1;padding:10px 14px;border:2px solid #e2e8f0;border-radius:8px;font-size:14px}.chat-input:focus{outline:none;border-color:#f0bc3b}.chat-send-btn{padding:10px 20px;background:linear-gradient(135deg,#f0bc3b 0%,#e8a825 100%);color:#2d1b00;border:none;border-radius:8px;cursor:pointer;font-weight:600;transition:all 0.3s;box-shadow:0 2px 8px rgba(240,188,59,0.3)}.chat-send-btn:hover{transform:translateY(-1px);box-shadow:0 4px 12px rgba(240,188,59,0.4)}.chat-send-btn:disabled{opacity:0.6;cursor:not-allowed;transform:none}.quick-btn{padding:6px 10px;background:#fff3dc;border:1px solid #f0bc3b;border-radius:6px;font-size:12px;cursor:pointer;margin-right:8px;margin-bottom:8px;color:#2d1b00;transition:all 0.3s}.quick-btn:hover{background:#f0bc3b;color:white;transform:translateY(-1px)}.contact-author{display:inline-flex;align-items:center;gap:5px;padding:6px 12px;background:#f0bc3b;border:2px solid #f0bc3b;border-radius:6px;color:#2d1b00;text-decoration:none;font-size:12px;font-weight:700;transition:all 0.3s;margin-left:10px;box-shadow:0 2px 8px rgba(240,188,59,0.3)}.contact-author:hover{transform:translateY(-1px);box-shadow:0 4px 12px rgba(240,188,59,0.4)}.footer{background:linear-gradient(135deg,#f0bc3b 0%,#e8a825 100%);color:#2d1b00;padding:25px 30px;border-radius:12px;margin-top:20px;text-align:center;box-shadow:0 4px 20px rgba(240,188,59,0.3)}.footer-title{font-size:16px;font-weight:700;margin-bottom:15px}.footer-links{display:flex;justify-content:center;gap:20px;flex-wrap:wrap}.footer-link{display:inline-flex;align-items:center;gap:8px;padding:12px 24px;background:rgba(255,255,255,0.3);border:2px solid rgba(255,255,255,0.5);border-radius:10px;color:#2d1b00;text-decoration:none;font-size:14px;font-weight:600;transition:all 0.3s;box-shadow:0 2px 8px rgba(0,0,0,0.1)}.footer-link:hover{background:rgba(255,255,255,0.5);transform:translateY(-2px);box-shadow:0 4px 12px rgba(0,0,0,0.15)}.footer-note{margin-top:15px;font-size:11px;opacity:0.75}.position-card,.trade-card{background:#f8fafc;border-radius:8px;padding:12px;margin-bottom:10px;border-left:3px solid #f0bc3b}.position-card-header,.trade-card-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;padding-bottom:8px;border-bottom:1px solid #e2e8f0}.position-card-header .symbol,.trade-card-header .symbol{font-size:16px;font-weight:700;color:#1e293b}.position-card-header .side,.trade-card-header .side{font-size:13px;color:#64748b;font-weight:600}.position-card-row,.trade-card-row{display:flex;justify-content:space-between;align-items:center;padding:6px 0;font-size:13px}.position-card-row .label,.trade-card-row .label{color:#64748b;font-weight:500}.position-card-row .value,.trade-card-row .value{color:#1e293b;font-weight:600;text-align:right}@media(max-width:768px){body{padding:8px;overflow-x:hidden}.container{max-width:100%;width:100%;padding:0}.header{padding:12px;flex-direction:column;align-items:center;gap:8px;margin-bottom:12px}.logo{width:45px;height:45px}.header-content{width:100%;text-align:center}.header h1{font-size:15px;margin-bottom:6px;line-height:1.3}.header-subtitle{font-size:11px}.header-actions{display:flex;flex-direction:row;justify-content:center;align-items:center;gap:6px;margin-top:8px;flex-wrap:wrap}.performance-badge{font-size:12px;padding:6px 12px;margin:3px}.control-btn{padding:6px 12px;font-size:11px;margin-left:0}.mode-badge{margin-left:0;font-size:11px}.contact-author{margin-left:0}.position-card,.trade-card{display:block}.decision-analysis,.decision-risk{font-size:13px !important;line-height:1.7;margin-bottom:10px}#latestDecision{font-size:14px !important;line-height:1.7}#latestDecision p{margin-bottom:8px}#latestDecision strong{font-size:13px}#aiAnalysis{font-size:14px !important;line-height:1.7}#aiAnalysis p{margin-bottom:8px}.experiment-info{padding:8px 12px;gap:8px;font-size:10px;text-align:left;justify-content:flex-start;flex-wrap:wrap;flex-direction:column}.experiment-info-item{width:100%;text-align:left}.experiment-info-item{font-size:10px}.stats-grid{grid-template-columns:repeat(2,1fr);gap:8px;margin-bottom:12px}.stat-box{padding:10px;border-radius:8px}.stat-label{font-size:10px}.stat-value{font-size:18px}.grid{grid-template-columns:1fr;gap:12px}.card{padding:12px;border-radius:8px;margin-bottom:12px;width:100%;box-sizing:border-box}.card-title{font-size:14px;margin-bottom:10px;font-weight:600}.chart-container{height:200px;width:100%;position:relative;overflow:visible;margin-top:15px;padding-top:15px;z-index:10}.chat-container{height:300px;width:100%}.message{margin-bottom:10px}.message-content{max-width:88%;font-size:12px;padding:8px;overflow-wrap:break-word;word-wrap:break-word;hyphens:auto;line-height:1.5}.message-ai-decision{padding:8px;overflow-wrap:break-word;word-wrap:break-word;font-size:11px}.message-ai-decision.executed::before{font-size:10px;padding:2px 6px;margin-bottom:6px}.decision-content{font-size:11px;overflow-wrap:break-word;word-wrap:break-word;background:transparent !important}.decision-analysis,.decision-risk{font-size:11px;line-height:1.6;overflow-wrap:break-word;word-wrap:break-word;white-space:normal;margin-bottom:8px;background:transparent !important}.think-box{margin-bottom:8px}.think-title{font-size:10px}.think-content{font-size:9px;padding:6px;height:120px;overflow-y:auto;overflow-wrap:break-word;word-wrap:break-word;white-space:pre-wrap;background:#fff;border-radius:4px}.chat-input-area{flex-direction:row;gap:6px;width:100%}.chat-input{font-size:13px;padding:8px;flex:1;min-width:0}.chat-send-btn{padding:8px 12px;font-size:12px;white-space:nowrap}.quick-btn{padding:4px 7px;font-size:10px;margin:0 3px 5px 0;display:inline-block}.loading,.no-data{font-size:12px;padding:15px}.contact-author{margin-left:0;margin-top:5px;font-size:10px;padding:4px 8px}.desktop-buttons{display:none !important}.mobile-buttons{display:block !important}.mobile-btn-row{justify-content:center !important}.mobile-btn{font-size:10px;padding:7px 10px}.mobile-btn.active{padding:6px 9px}.footer{padding:12px;margin-top:12px;border-radius:8px}.footer-title{font-size:13px;margin-bottom:10px}.footer-links{gap:8px;flex-direction:column}.footer-link{padding:8px 12px;font-size:11px;width:100%;box-sizing:border-box;justify-content:center}.footer-note{font-size:9px;margin-top:8px}#latestDecision{font-size:12px;line-height:1.6}#latestDecision p{margin-bottom:6px;overflow-wrap:break-word;word-wrap:break-word}#latestDecision strong{font-size:11px}#aiAnalysis{font-size:12px}#aiAnalysis p{overflow-wrap:break-word;word-wrap:break-word}}</style></head><body><div class="container"><div class="header"><div class="header-content"><div style="display:flex;align-items:center;flex-wrap:wrap;gap:10px"><h1><img src="https://bitechain.io/assets/images/logo/soltracker-logo.png" alt="Logo" style="width:36px;height:36px;vertical-align:middle;margin-right:10px"/> 追踪狗AI交易系统（内测版）<span id="modelIndicator" style="font-size:18px;font-weight:600;margin-left:12px;color:#2d1b00"></span></h1><span class="performance-badge" id="profitBadge">--</span><span class="performance-badge" id="annualBadge">--</span><span class="performance-badge neutral" id="drawdownBadge">--</span><span class="performance-badge neutral" id="sharpeBadge">--</span></div><div class="header-subtitle">更新时间: <span id="updateTime">--</span></div><div class="header-subtitle" style="margin-top:8px"><span style="color:#2d1b00;font-weight:600">AI状态:</span> <span id="aiStatusIndicator" style="display:inline-block">加载中...</span></div><div class="button-row-top desktop-buttons"><button class="unified-btn" id="cooldownBtn" onclick="checkCooldownDetails()">⏰ 正常交易</button><button class="unified-btn" id="modeBtn" onclick="toggleMode()">🧪 测试</button><a href="https://x.com/bitechain" target="_blank" rel="noopener noreferrer" class="unified-btn">📧 联系作者</a></div><div class="button-row-bottom desktop-buttons"><button class="unified-btn active" onclick="switchModel('combined')" id="tab-combined">📊 综合</button><button class="unified-btn" onclick="switchModel('deepseek')" id="tab-deepseek">🤖 DeepSeek</button><button class="unified-btn" onclick="switchModel('qwen')" id="tab-qwen">🧠 通义千问</button></div><div class="mobile-buttons" style="width:100%;margin-top:8px"><div class="mobile-btn-row" style="display:flex;flex-direction:row;justify-content:center;align-items:center;gap:8px;flex-wrap:wrap;width:100%"><button class="mobile-btn" id="cooldownBtnMobile" onclick="checkCooldownDetails()" style="flex:0 0 auto;margin:0">⏰ 正常交易</button><button class="mobile-btn" id="modeBtnMobile" onclick="toggleMode()" style="flex:0 0 auto;margin:0">🧪 测试</button><a href="https://x.com/bitechain" target="_blank" rel="noopener noreferrer" class="mobile-btn" style="flex:0 0 auto;margin:0">📧 联系作者</a></div><div class="mobile-btn-row" style="display:flex;flex-direction:row;justify-content:center;align-items:center;gap:8px;flex-wrap:wrap;width:100%;margin-top:8px"><button class="mobile-btn active" onclick="switchModel('combined')" id="tab-combined-mobile" style="flex:0 0 auto;margin:0">📊 综合</button><button class="mobile-btn" onclick="switchModel('deepseek')" id="tab-deepseek-mobile" style="flex:0 0 auto;margin:0">🤖 DeepSeek</button><button class="mobile-btn" onclick="switchModel('qwen')" id="tab-qwen-mobile" style="flex:0 0 auto;margin:0">🧠 通义千问</button></div></div><div class="experiment-info" id="experimentInfo"><div class="experiment-info-item">💰 <strong>初始资金:</strong> <span id="initCapital">--</span></div><div class="experiment-info-item">🪙 <strong>交易币种:</strong> <span id="tradingPairs">--</span></div><div class="experiment-info-item">📊 <strong>杠杆率:</strong> <span id="maxLeverage">--</span></div><div class="experiment-info-item">⚡ <strong>策略:</strong> <span id="strategy">--</span></div><div class="experiment-info-item">🎯 <strong>风控:</strong> <span id="riskControl">--</span></div></div></div><div class="header-right"><div class="visitor-count" id="visitorCount">👀 <span id="visitorNum">--</span> 人看过</div><button class="share-btn" onclick="shareToFriends()">📢 分享给好友，一起来围观</button></div></div><div class="stats-grid"><div class="stat-box"><div class="stat-label">总资产</div><div class="stat-value" id="totalAssets">--</div></div><div class="stat-box"><div class="stat-label">可用余额</div><div class="stat-value" id="balance">--</div></div><div class="stat-box"><div class="stat-label">保证金占用</div><div class="stat-value" id="positionValue">--</div></div><div class="stat-box"><div class="stat-label">未实现盈亏</div><div class="stat-value" id="unrealizedPnl">--</div></div><div class="stat-box"><div class="stat-label">账户总盈利</div><div class="stat-value" id="totalProfit">--</div></div></div><div class="grid"><div><div class="card"><div class="card-title">📈 盈亏曲线 / 💹 代币价格 <button class="time-range-btn" onclick="toggleChartMode()" style="margin-left:10px" id="chartModeBtn">切换到价格</button></div><div class="chart-controls"><button class="time-range-btn active" onclick="setTimeRange('all')">全部</button><button class="time-range-btn" onclick="setTimeRange('month')">当月</button><button class="time-range-btn" onclick="setTimeRange('week')">当周</button><button class="time-range-btn" onclick="setTimeRange('day')">当天</button><div class="date-picker-group"><input type="date" id="startDate" class="date-picker-input"/><span style="color:#64748b">至</span><input type="date" id="endDate" class="date-picker-input"/><button class="time-range-btn" onclick="setCustomRange()" style="padding:6px 10px">查询</button></div></div><div class="chart-controls" id="symbolControls" style="display:none"><button class="symbol-btn active" onclick="switchSymbol('BTC')">BTC</button><button class="symbol-btn" onclick="switchSymbol('ETH')">ETH</button><button class="symbol-btn" onclick="switchSymbol('SOL')">SOL</button><button class="symbol-btn" onclick="switchSymbol('BNB')">BNB</button><button class="symbol-btn" onclick="switchSymbol('XRP')">XRP</button><button class="symbol-btn" onclick="switchSymbol('DOGE')">DOGE</button><button class="symbol-btn" onclick="switchSymbol('LTC')">LTC</button></div><div id="symbolStats" style="display:none;margin:10px 0;padding:10px;background:#f8fafc;border-radius:6px;font-size:13px;color:#334155"><strong id="symbolStatsSymbol">BTC</strong> | 总盈亏: <span id="symbolStatsPnl" style="font-weight:600">--</span> | 胜率: <span id="symbolStatsWinRate" style="font-weight:600">--</span> | 交易次数: <span id="symbolStatsTrades" style="font-weight:600">--</span></div><div class="chart-container"><div id="pnlChart"><canvas id="pnlChartCanvas"></canvas></div></div></div><div class="card"><div class="card-title">💼 当前持仓</div><div id="positionsTable"><div class="loading">加载中...</div></div><div class="pagination" id="positionsPagination" style="display:none;margin-top:15px;text-align:center"><button onclick="changePositionPage(-1)" style="padding:6px 12px;margin:0 5px;border:1px solid #f0bc3b;background:white;color:#2d1b00;border-radius:4px;cursor:pointer">上一页</button><span id="positionsPageInfo" style="margin:0 10px;color:#64748b;font-size:13px">第 1 页</span><button onclick="changePositionPage(1)" style="padding:6px 12px;margin:0 5px;border:1px solid #f0bc3b;background:white;color:#2d1b00;border-radius:4px;cursor:pointer">下一页</button></div></div><div class="card"><div class="card-title">📝 最近交易</div><div id="tradesTable"><div class="loading">加载中...</div></div><div class="pagination" id="tradesPagination" style="display:none;margin-top:15px;text-align:center"><button onclick="changeTradePage(-1)" style="padding:6px 12px;margin:0 5px;border:1px solid #f0bc3b;background:white;color:#2d1b00;border-radius:4px;cursor:pointer">上一页</button><span id="tradesPageInfo" style="margin:0 10px;color:#64748b;font-size:13px">第 1 页</span><button onclick="changeTradePage(1)" style="padding:6px 12px;margin:0 5px;border:1px solid #f0bc3b;background:white;color:#2d1b00;border-radius:4px;cursor:pointer">下一页</button></div></div><div class="card"><div class="card-title">⚡ 最新决策</div><div id="latestDecision" style="line-height:1.6;color:#555;font-size:14px"><div class="loading">加载中...</div></div></div></div><div><div class="card"><div class="card-title">💬 AI决策记录 & 对话</div><div style="margin-bottom:10px"><button class="quick-btn" onclick="sendQuick('当前持仓分析')">持仓分析</button><button class="quick-btn" onclick="sendQuick('是否调仓？')">调仓建议</button><button class="quick-btn" onclick="sendQuick('风险评估')">风险评估</button></div><div class="chat-container"><div class="chat-messages" id="chatMessages"><div class="loading">加载AI决策...</div></div><div class="chat-input-area"><input type="text" class="chat-input" id="chatInput" placeholder="输入问题..." onkeypress="if(event.keyCode==13)sendMsg()"/><button class="chat-send-btn" id="sendBtn" onclick="sendMsg()">发送</button></div></div></div><div class="card"><div class="card-title">🤖 AI最新分析</div><div id="aiAnalysis" style="line-height:1.6;color:#555;font-size:14px"><div class="loading">加载中...</div></div></div></div></div><div class="footer"><div class="footer-title">🔥 相关产品推荐</div><div class="footer-links"><a href="https://bitechain.io/" target="_blank" rel="noopener noreferrer" class="footer-link">🐶 追踪狗聪明钱包<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6M15 3h6v6M10 14L21 3"/></svg></a><a href="https://bitechain.xyz/" target="_blank" rel="noopener noreferrer" class="footer-link">🎯 追踪狗个人导航页<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6M15 3h6v6M10 14L21 3"/></svg></a></div><div class="footer-note">Powered by 追踪狗团队 | 内测展示版本</div></div></div><script>let chart=null,priceChart=null,lastDecisionCount=0,currentModel='combined',compareChart=null,deepseekChart=null,qwenChart=null,currentTimeRange='all',customStartDate='',customEndDate='',chartMode='pnl',currentSymbol='BTC';function toggleChartMode(){chartMode=chartMode==='pnl'?'price':'pnl';document.getElementById('chartModeBtn').textContent=chartMode==='pnl'?'切换到价格':'切换到盈亏';document.getElementById('symbolControls').style.display=chartMode==='price'?'flex':'none';const symbolStatsDiv=document.getElementById('symbolStats');if(symbolStatsDiv){symbolStatsDiv.style.display=chartMode==='price'?'block':'none'}if(chartMode==='pnl'){if(priceChart&&priceChart.remove){priceChart.remove();priceChart=null}const container=document.getElementById('pnlChart');container.innerHTML='<canvas id="pnlChartCanvas"></canvas>'}else{if(chart&&chart.destroy){chart.destroy();chart=null}}if(window.lastSummaryData){updateUI(window.lastSummaryData);updatePos(window.lastSummaryData);updateTrades(window.lastSummaryData)}if(chartMode==='pnl'){updateChart(window.lastSummaryData)}else{loadPriceChart()}}let symbolTimeout=null;function switchSymbol(sym){currentSymbol=sym;document.querySelectorAll('.symbol-btn').forEach(b=>b.classList.remove('active'));event.target.classList.add('active');if(symbolTimeout)clearTimeout(symbolTimeout);symbolTimeout=setTimeout(()=>{loadPriceChart();if(window.lastSummaryData){updatePos(window.lastSummaryData);updateTrades(window.lastSummaryData)}},200)}async function loadPriceChart(){if(chartMode!=='price')return;try{console.log('🔍 当前时间范围:',currentTimeRange);let params=new URLSearchParams({model:currentModel,symbol:currentSymbol});if(currentTimeRange){params.append('range',currentTimeRange)}if(customStartDate&&customEndDate){params.append('start_date',customStartDate);params.append('end_date',customEndDate)}console.log('📡 请求价格数据:',`/trading-price-data?${params}`);const r=await fetch(`/trading-price-data?${params}`);const data=await r.json();console.log('📥 收到数据:',data);console.log('📊 K线数量:',data.kline_data?.length);console.log('📍 订单标注:',data.trade_markers?.length);const symbolStatsDiv=document.getElementById('symbolStats');if(symbolStatsDiv&&data.symbol_stats){document.getElementById('symbolStatsSymbol').textContent=currentSymbol;const pnl=data.symbol_stats.total_pnl||0;const winRate=data.symbol_stats.win_rate||0;const tradeCount=data.symbol_stats.trade_count||0;const pnlSpan=document.getElementById('symbolStatsPnl');pnlSpan.textContent=`${pnl>=0?'+':''}${pnl.toFixed(2)} U`;pnlSpan.style.color=pnl>=0?'#22c55e':'#ef4444';document.getElementById('symbolStatsWinRate').textContent=`${winRate.toFixed(1)}%`;document.getElementById('symbolStatsTrades').textContent=`${tradeCount}笔`;symbolStatsDiv.style.display='block'}else if(symbolStatsDiv){symbolStatsDiv.style.display='none'}if(!data.kline_data||data.kline_data.length===0){console.warn('❌ 无价格数据');return}const container=document.getElementById('pnlChart');container.innerHTML='';if(priceChart&&priceChart.remove){priceChart.remove();priceChart=null}const isMobile=window.innerWidth<=768;priceChart=LightweightCharts.createChart(container,{width:container.clientWidth,height:isMobile?200:450,layout:{background:{color:'#ffffff'},textColor:'#333'},localization:{locale:'zh-CN',timeFormatter:businessDayOrTimestamp=>{try{if(typeof businessDayOrTimestamp==='number'){const date=new Date(businessDayOrTimestamp*1000);if(isNaN(date.getTime()))return'';const month=String(date.getMonth()+1).padStart(2,'0');const day=String(date.getDate()).padStart(2,'0');const hour=String(date.getHours()).padStart(2,'0');const minute=String(date.getMinutes()).padStart(2,'0');return`${month}-${day} ${hour}:${minute}`}return String(businessDayOrTimestamp||'')}catch(e){return''}}},grid:{vertLines:{color:'#f0f0f0'},horzLines:{color:'#f0f0f0'}},crosshair:{mode:LightweightCharts.CrosshairMode.Normal},rightPriceScale:{borderColor:'#cccccc'},timeScale:{borderColor:'#cccccc',timeVisible:true,secondsVisible:false,tickMarkFormatter:(time)=>{try{if(!time)return'';const date=new Date(time*1000);if(isNaN(date.getTime()))return'';const month=String(date.getMonth()+1).padStart(2,'0');const day=String(date.getDate()).padStart(2,'0');const hour=String(date.getHours()).padStart(2,'0');const minute=String(date.getMinutes()).padStart(2,'0');return`${month}-${day} ${hour}:${minute}`}catch(e){return''}}}});const candlestickSeries=priceChart.addCandlestickSeries({upColor:'#10b981',downColor:'#ef4444',borderUpColor:'#10b981',borderDownColor:'#ef4444',wickUpColor:'#10b981',wickDownColor:'#ef4444'});const candleData=data.kline_data.map(k=>{const parts=k.timestamp.match(/(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})/);if(parts){const bjTime=new Date(parseInt(parts[1]),parseInt(parts[2])-1,parseInt(parts[3]),parseInt(parts[4]),parseInt(parts[5]),parseInt(parts[6]));const open=parseFloat(k.open);const high=parseFloat(k.high);const low=parseFloat(k.low);const close=parseFloat(k.close);if(isNaN(open)||isNaN(high)||isNaN(low)||isNaN(close)||open<=0||high<=0||low<=0||close<=0){console.warn('⚠️ 无效K线数据:',k);return null}return{time:Math.floor(bjTime.getTime()/1000),open:open,high:high,low:low,close:close}}return null}).filter(d=>d!==null);console.log('✅ 有效K线数据:',candleData.length+'条');if(candleData.length>0){console.log('📊 K线范围:',new Date(candleData[0].time*1000).toLocaleString(),'至',new Date(candleData[candleData.length-1].time*1000).toLocaleString())}candlestickSeries.setData(candleData);const markers=[];if(data.trade_markers&&data.trade_markers.length>0){data.trade_markers.forEach(m=>{const parts=m.timestamp.match(/(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})/);if(parts){const bjTime=new Date(Date.UTC(parseInt(parts[1]),parseInt(parts[2])-1,parseInt(parts[3]),parseInt(parts[4])-8,parseInt(parts[5]),parseInt(parts[6])));const time=Math.floor(bjTime.getTime()/1000);if(m.type==='open'){markers.push({time:time,position:m.side==='多'?'belowBar':'aboveBar',color:m.side==='多'?'#10b981':'#ef4444',shape:m.side==='多'?'arrowUp':'arrowDown',text:'B',size:isMobile?0.8:1})}else{markers.push({time:time,position:'aboveBar',color:'#3b82f6',shape:'arrowDown',text:'S',size:isMobile?0.8:1})}}})}candlestickSeries.setMarkers(markers);const tooltip=document.createElement('div');tooltip.style.cssText='position:absolute;display:none;padding:8px 12px;background:rgba(0,0,0,0.85);color:white;border-radius:6px;font-size:12px;pointer-events:none;z-index:1000;max-width:300px;line-height:1.5;box-shadow:0 4px 12px rgba(0,0,0,0.3)';container.appendChild(tooltip);priceChart.subscribeCrosshairMove(param=>{if(!param.time||!param.point){tooltip.style.display='none';return}const matchedMarker=data.trade_markers?.find(m=>{const parts=m.timestamp.match(/(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})/);if(parts){const bjTime=new Date(Date.UTC(parseInt(parts[1]),parseInt(parts[2])-1,parseInt(parts[3]),parseInt(parts[4])-8,parseInt(parts[5]),parseInt(parts[6])));const time=Math.floor(bjTime.getTime()/1000);return Math.abs(time-param.time)<900}return false});if(matchedMarker){const modelBadge=currentModel==='combined'&&matchedMarker.model?`<span style="display:inline-block;padding:2px 6px;background:${matchedMarker.model==='deepseek'?'#3b82f6':'#f97316'};color:white;border-radius:4px;font-size:10px;margin-left:6px">${matchedMarker.model==='deepseek'?'DS':'QW'}</span>`:'';const typeText=matchedMarker.type==='open'?(matchedMarker.side==='多'?'开多':'开空'):'平仓';const color=matchedMarker.type==='open'?(matchedMarker.side==='多'?'#10b981':'#ef4444'):'#3b82f6';let content=`<strong style="color:${color}">${typeText}${modelBadge}</strong><br/>`;if(matchedMarker.type==='close'){const pnlColor=matchedMarker.pnl>=0?'#10b981':'#ef4444';const pnlText=matchedMarker.pnl>=0?'+'+matchedMarker.pnl.toFixed(2):matchedMarker.pnl.toFixed(2);content+=`开仓: ${matchedMarker.open_price} U<br/>`;content+=`平仓: ${matchedMarker.price} U<br/>`;content+=`盈亏: <span style="color:${pnlColor};font-weight:600">${pnlText} U</span><br/>`;if(matchedMarker.hold_time){content+=`持仓: ${matchedMarker.hold_time}<br/>`}}else{content+=`价格: ${matchedMarker.price} U<br/>`}content+=`时间: ${matchedMarker.timestamp}<br/>`;if(matchedMarker.reason){content+=`理由: ${matchedMarker.reason}`}tooltip.innerHTML=content;tooltip.style.display='block';tooltip.style.left=param.point.x+15+'px';tooltip.style.top=param.point.y-60+'px'}else{tooltip.style.display='none'}});priceChart.timeScale().fitContent();window.addEventListener('resize',()=>{if(priceChart&&chartMode==='price'){priceChart.applyOptions({width:container.clientWidth})}})}catch(e){console.error('❌ 加载价格图表失败:',e)}}function setTimeRange(range){currentTimeRange=range;customStartDate='';customEndDate='';document.querySelectorAll('.time-range-btn').forEach(btn=>btn.classList.remove('active'));event.target.classList.add('active');refresh()}function setCustomRange(){const start=document.getElementById('startDate').value;const end=document.getElementById('endDate').value;if(!start||!end){alert('请选择开始和结束日期');return}if(start>end){alert('开始日期不能晚于结束日期');return}customStartDate=start;customEndDate=end;currentTimeRange='custom';document.querySelectorAll('.time-range-btn').forEach(btn=>btn.classList.remove('active'));refresh()}
function switchModel(model){currentModel=model;lastDecisionCount=0;const indicator=document.getElementById('modelIndicator');document.querySelectorAll('#tab-combined,#tab-deepseek,#tab-qwen,#tab-combined-mobile,#tab-deepseek-mobile,#tab-qwen-mobile').forEach(btn=>{btn.classList.remove('active')});const desktopBtn=document.getElementById(`tab-${model}`);const mobileBtn=document.getElementById(`tab-${model}-mobile`);if(desktopBtn)desktopBtn.classList.add('active');if(mobileBtn)mobileBtn.classList.add('active');if(model==='combined'){indicator.textContent=''}else if(model==='deepseek'){indicator.textContent='🤖 DeepSeek'}else if(model==='qwen'){indicator.textContent='🧠 通义千问'}const chatDiv=document.getElementById('chatMessages');chatDiv.innerHTML='<div class="loading">加载AI决策...</div>';const aiAnalysisDiv=document.getElementById('aiAnalysis');aiAnalysisDiv.innerHTML='<div class="loading">加载中...</div>';document.getElementById('latestDecision').innerHTML='<div class="loading">加载中...</div>';document.getElementById('tradesTable').innerHTML='<div class="loading">加载中...</div>';document.getElementById('positionsTable').innerHTML='<div class="loading">加载中...</div>';refresh()}
function handleStatusClick(){if(currentModel==='combined'){alert('请先选择具体的模型（DeepSeek或通义千问）再切换模式');return}const pwd=prompt('请输入控制密码:');if(!pwd)return;fetch('/trading-control',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'toggle_mode',password:pwd,model:currentModel})}).then(r=>r.json()).then(d=>{alert(d.message||d.error);refresh()}).catch(e=>{alert('操作失败:'+e)})}
function showCompareView(){document.querySelector('.stats-grid').style.display='none';document.querySelector('.grid').style.display='none';let compareDiv=document.getElementById('compareView');if(!compareDiv){compareDiv=document.createElement('div');compareDiv.id='compareView';compareDiv.innerHTML='<div class="card"><div class="card-title">📊 模型对比 - 盈亏曲线</div><div class="chart-container"><canvas id="compareChart"></canvas></div></div><div class="card"><div class="card-title">📈 关键指标对比</div><table style="width:100%"><thead><tr><th>指标</th><th>🤖 DeepSeek</th><th>🧠 通义千问</th><th>差异</th></tr></thead><tbody id="compareTableBody"><tr><td colspan="4" class="loading">加载中...</td></tr></tbody></table></div>';document.querySelector('.container').insertBefore(compareDiv,document.querySelector('.footer'))}compareDiv.style.display='block';loadCompareData()}
function hideCompareView(){const compareDiv=document.getElementById('compareView');if(compareDiv)compareDiv.style.display='none';document.querySelector('.stats-grid').style.display='grid';document.querySelector('.grid').style.display='grid'}
async function loadCompareData(){try{const [dsData,qwData]=await Promise.all([fetch('/trading-summary?model=deepseek').then(r=>r.json()),fetch('/trading-summary?model=qwen').then(r=>r.json())]);await drawCompareChart(dsData,qwData);fillCompareTable(dsData,qwData)}catch(e){console.error('加载对比数据失败:',e)}}
async function drawCompareChart(dsData,qwData){try{const [dsPnl,qwPnl]=await Promise.all([fetch('/trading-pnl?limit=96&model=deepseek').then(r=>r.json()),fetch('/trading-pnl?limit=96&model=qwen').then(r=>r.json())]);const dsAssets=dsPnl.pnl_data?.map(d=>parseFloat(d['总资产']||d['total_assets']||0))||[];const qwAssets=qwPnl.pnl_data?.map(d=>parseFloat(d['总资产']||d['total_assets']||0))||[];const labels=dsPnl.pnl_data?.map(d=>(d['时间']||d['timestamp']||'').split(' ')[1]||'')||[];const ctx=document.getElementById('compareChart').getContext('2d');if(compareChart)compareChart.destroy();compareChart=new Chart(ctx,{type:'line',data:{labels,datasets:[{label:'DeepSeek',data:dsAssets,borderColor:'#3b82f6',backgroundColor:'rgba(59,130,246,0.1)',borderWidth:2.5,tension:0.4},{label:'通义千问',data:qwAssets,borderColor:'#f97316',backgroundColor:'rgba(249,115,22,0.1)',borderWidth:2.5,tension:0.4}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{position:'top'},tooltip:{mode:'index',intersect:false}},scales:{y:{beginAtZero:false},x:{ticks:{maxTicksLimit:8}}}}})}catch(e){console.error(e)}}
function fillCompareTable(dsData,qwData){const tbody=document.getElementById('compareTableBody');if(!dsData?.status||!qwData?.status){tbody.innerHTML='<tr><td colspan="4">数据加载失败</td></tr>';return}const metrics=[{name:'总资产',key:'total_assets',unit:'U'},{name:'盈利率',key:'profit_rate',unit:'%'},{name:'年化收益',key:'annualized_return',unit:'%'},{name:'最大回撤',key:'max_drawdown',unit:'%'},{name:'夏普比率',key:'sharpe_ratio',unit:''},{name:'持仓数',key:'position_count',unit:'个'}];let html='';metrics.forEach(m=>{const dsVal=dsData.status[m.key]||0;const qwVal=qwData.status[m.key]||0;const diff=qwVal-dsVal;const diffColor=diff>=0?'#10b981':'#ef4444';html+=`<tr><td><strong>${m.name}</strong></td><td>${dsVal.toFixed(2)}${m.unit}</td><td>${qwVal.toFixed(2)}${m.unit}</td><td style="color:${diffColor}">${diff>=0?'+':''}${diff.toFixed(2)}${m.unit}</td></tr>`});tbody.innerHTML=html}
function formatAIReply(t){if(!t)return'';let f=t.replace(/\*\*(.*?)\*\*/g,'<strong>$1</strong>');const ls=f.split('\\n');let h='',inL=false,inN=false;for(let ln of ls){ln=ln.trim();if(!ln){if(inL){h+='</ul>';inL=false}if(inN){h+='</ol>';inN=false}h+='<br>';continue}if(/^\\d+\\.\\s+\\*\\*/.test(ln)){if(inL){h+='</ul>';inL=false}if(!inN){h+='<ol style="margin:8px 0;padding-left:20px">';inN=true}ln=ln.replace(/^\\d+\\.\\s+/,'');h+=`<li style="margin:4px 0">${ln}</li>`}else if(/^[✅❌⚠️🔹▪️•-]\\s+/.test(ln)){if(inN){h+='</ol>';inN=false}if(!inL){h+='<ul style="margin:8px 0;padding-left:20px;list-style:none">';inL=true}h+=`<li style="margin:4px 0">${ln}</li>`}else if(/^\\d+\\.\\s+/.test(ln)){if(inL){h+='</ul>';inL=false}if(!inN){h+='<ol style="margin:8px 0;padding-left:20px">';inN=true}ln=ln.replace(/^\\d+\\.\\s+/,'');h+=`<li style="margin:4px 0">${ln}</li>`}else{if(inL){h+='</ul>';inL=false}if(inN){h+='</ol>';inN=false}h+=ln+'<br>'}}if(inL)h+='</ul>';if(inN)h+='</ol>';return h}
async function load(){try{let params=new URLSearchParams({model:currentModel});if(currentTimeRange!=='all'){params.append('range',currentTimeRange)}if(customStartDate&&customEndDate){params.append('start_date',customStartDate);params.append('end_date',customEndDate)}const endpoint=currentModel==='combined'?`/trading-combined?${params}`:`/trading-summary?${params}`;const r=await fetch(endpoint);return await r.json()}catch(e){return null}}function calculateRemaining(pauseUntil){if(!pauseUntil)return'';try{const until=new Date(pauseUntil.replace(' ','T'));until.setHours(until.getHours()-8);const now=new Date();const diff=until-now;if(diff<=0)return'';const hours=Math.floor(diff/3600000);const minutes=Math.floor((diff%3600000)/60000);if(hours>24){return'(明日恢复)'}else if(hours>0){return'('+hours+'h'+minutes+'m)'}else{return'('+minutes+'m)'}}catch(e){console.error('计算剩余时间失败:',e);return''}}
function updateCooldownStatus(d){if(!d)return;const badge=document.getElementById('cooldownBadge');if(!badge)return;if(currentModel==='combined'){const dsStatus=d.models?.deepseek?.cooldown_status;const qwStatus=d.models?.qwen?.cooldown_status;if(!dsStatus&&!qwStatus){badge.style.display='none';return}let statusText='';let isPaused=false;if(dsStatus?.is_paused||qwStatus?.is_paused){isPaused=true;if(dsStatus?.is_paused&&qwStatus?.is_paused){statusText='❄️ 双模型冷静期'}else if(dsStatus?.is_paused){statusText='❄️ DeepSeek冷静期'}else{statusText='❄️ 通义千问冷静期'}let earliestUntil=null;if(dsStatus?.pause_until)earliestUntil=dsStatus.pause_until;if(qwStatus?.pause_until){if(!earliestUntil||qwStatus.pause_until<earliestUntil){earliestUntil=qwStatus.pause_until}}if(earliestUntil){const remaining=calculateRemaining(earliestUntil);if(remaining)statusText+=' '+remaining}}else{statusText='✅ 正常交易'}badge.textContent=statusText;badge.className=isPaused?'cooldown-badge cooldown-paused':'cooldown-badge cooldown-normal';badge.style.display='inline-block'}else{const status=d.cooldown_status;if(!status){badge.style.display='none';return}if(status.is_paused){let statusText='❄️ '+status.pause_reason;if(status.pause_until){const remaining=calculateRemaining(status.pause_until);if(remaining)statusText+=' '+remaining}badge.textContent=statusText;badge.className='cooldown-badge cooldown-paused'}else{badge.textContent='✅ 正常交易';badge.className='cooldown-badge cooldown-normal'}badge.style.display='inline-block'}}
function updateUI(d){if(!d||!d.status)return;const s=d.status;const serverTime=s.timestamp||'';if(serverTime){document.getElementById('updateTime').textContent=serverTime}else{document.getElementById('updateTime').textContent='--'}const balance=s.usdt_balance||0;const pnl=s.unrealized_pnl||0;const totalAssets=s.total_assets||0;const initialCapital=currentModel==='combined'?200:100;const totalProfit=totalAssets-initialCapital;const totalMargin=d.positions?d.positions.reduce((sum,p)=>sum+(p.margin||0),0):0;document.getElementById('totalAssets').textContent=totalAssets.toFixed(2)+' U';document.getElementById('balance').textContent=balance.toFixed(2)+' U';document.getElementById('positionValue').textContent=totalMargin.toFixed(2)+' U';const p=document.getElementById('unrealizedPnl');p.textContent=(pnl>=0?'+':'')+pnl.toFixed(2)+' U';p.style.color=pnl>=0?'#10b981':'#ef4444';const tp=document.getElementById('totalProfit');tp.textContent=(totalProfit>=0?'+':'')+totalProfit.toFixed(2)+' U';tp.style.color=totalProfit>=0?'#10b981':'#ef4444';updateStatusButton(d);const profitRate=s.profit_rate||0;const profitBadge=document.getElementById('profitBadge');profitBadge.textContent=(profitRate>=0?'📈 ':'📉 ')+'实际盈利 '+(profitRate>=0?'+':'')+profitRate.toFixed(2)+'%';profitBadge.className=profitRate>=0?'performance-badge positive':'performance-badge negative';const annualReturn=s.annualized_return||0;const annualBadge=document.getElementById('annualBadge');annualBadge.textContent='📊 年化 '+(annualReturn>=0?'+':'')+annualReturn.toFixed(1)+'%';annualBadge.className=annualReturn>=0?'performance-badge positive':'performance-badge negative';const maxDrawdown=s.max_drawdown||0;const drawdownBadge=document.getElementById('drawdownBadge');drawdownBadge.textContent='📉 最大回撤 '+maxDrawdown.toFixed(1)+'%';drawdownBadge.className='performance-badge neutral';const sharpeRatio=s.sharpe_ratio||0;const sharpeBadge=document.getElementById('sharpeBadge');sharpeBadge.textContent='📐 夏普 '+sharpeRatio.toFixed(2);sharpeBadge.className='performance-badge neutral';if(d.experiment_config){const cfg=d.experiment_config;document.getElementById('initCapital').textContent=cfg.initial_capital+'U';document.getElementById('tradingPairs').textContent=cfg.trading_pairs.join(', ');document.getElementById('maxLeverage').textContent=cfg.max_leverage;document.getElementById('strategy').textContent=cfg.strategy;document.getElementById('riskControl').textContent=cfg.risk_per_trade}if(currentModel==='combined'&&s.latest_model){const modelTag=s.latest_model==='DeepSeek'?'🤖 DeepSeek':'🧠 '+s.latest_model;document.getElementById('aiAnalysis').innerHTML='<p><strong>分析 ['+modelTag+']：</strong>'+formatAIReply(s.ai_analysis)+'</p><br><p><strong>风险 ['+modelTag+']：</strong>'+formatAIReply(s.risk_assessment||'无')+'</p>'}else if(s.ai_analysis){document.getElementById('aiAnalysis').innerHTML='<p><strong>分析：</strong>'+formatAIReply(s.ai_analysis)+'</p><br><p><strong>风险：</strong>'+formatAIReply(s.risk_assessment||'无')+'</p>'}}
async function updateAIStatus(){try{if(currentModel==='combined'){const [dsStatus,qwStatus]=await Promise.all([fetch('/trading-ai-status?model=deepseek').then(r=>r.json()),fetch('/trading-ai-status?model=qwen').then(r=>r.json())]);window.lastAIStatus={deepseek:dsStatus,qwen:qwStatus,model:'combined'};updateAIStatusDisplay(dsStatus,'deepseek');updateAIStatusDisplay(qwStatus,'qwen')}else{const status=await fetch(`/trading-ai-status?model=${currentModel}`).then(r=>r.json());window.lastAIStatus=status;updateAIStatusDisplay(status,currentModel)}}catch(e){console.error('获取AI状态失败:',e)}}function updateAIStatusDisplay(status,model){if(!status)return;const aiStatusDiv=document.getElementById('aiStatusIndicator');if(!aiStatusDiv)return;let statusHtml='';if(currentModel==='combined'){const existingContent=aiStatusDiv.innerHTML;const modelTag=model==='deepseek'?'🤖 DeepSeek':'🧠 通义千问';const statusInfo=`<span style="display:inline-block;padding:4px 10px;background:${status.status==='online'?'#d1fae5':status.status==='offline'?'#fee2e2':'#fef3c7'};color:${status.status==='online'?'#065f46':status.status==='offline'?'#991b1b':'#92400e'};border-radius:6px;margin:3px;font-size:11px;font-weight:600">${modelTag}: ${status.status_emoji} ${status.status_text}</span>`;if(existingContent.includes(modelTag)){aiStatusDiv.innerHTML=existingContent.replace(new RegExp(`<span[^>]*>${modelTag}:[^<]*</span>`),statusInfo.replace(/<span[^>]*>/,'').replace('</span>',''))}else{aiStatusDiv.innerHTML+=statusInfo}}else{const statusColor=status.status==='online'?'#10b981':status.status==='offline'?'#ef4444':status.status==='cooldown'?'#f59e0b':'#6b7280';aiStatusDiv.innerHTML=`<span style="display:inline-block;padding:6px 14px;background:${statusColor}15;color:${statusColor};border:2px solid ${statusColor};border-radius:8px;font-size:13px;font-weight:700;cursor:pointer" onclick="showAIStatusDetails()" title="点击查看详情">${status.status_emoji} AI ${status.status_text}</span>`}}function showAIStatusDetails(){if(!window.lastAIStatus){alert('正在加载状态数据...');return}const s=window.lastAIStatus;let msg=`🤖 AI状态详情\n\n`;msg+=`运行状态: ${s.status_text}\n`;msg+=`进程运行: ${s.is_running?'✅ 是':'❌ 否'}\n`;msg+=`数据更新: ${s.is_active?'✅ 正常':'⚠️ 异常'}\n`;if(s.last_update){msg+=`最后更新: ${s.last_update}\n`}msg+=`\n`;if(s.is_paused){msg+=`❄️ 冷却状态: ${s.pause_reason}\n`;if(s.pause_until){msg+=`恢复时间: ${s.pause_until}\n`}}if(s.test_mode!==null){msg+=`\n运行模式: ${s.test_mode?'🧪 测试模式':'🔴 实盘模式'}`}alert(msg)}function updateStatusButton(d){const cooldownBtn=document.getElementById('cooldownBtn');const modeBtn=document.getElementById('modeBtn');const cooldownBtnMobile=document.getElementById('cooldownBtnMobile');const modeBtnMobile=document.getElementById('modeBtnMobile');if(!cooldownBtn||!modeBtn)return;let cooldownText='⏰ 正常交易';let isPaused=false;if(currentModel==='combined'){const dsStatus=d.models?.deepseek?.cooldown_status;const qwStatus=d.models?.qwen?.cooldown_status;if(dsStatus?.is_paused||qwStatus?.is_paused){isPaused=true;cooldownText='❄️ 冷静期'}}else{const status=d.cooldown_status;if(status?.is_paused){isPaused=true;cooldownText='❄️ 冷静期'}}cooldownBtn.textContent=cooldownText;if(cooldownBtnMobile)cooldownBtnMobile.textContent=cooldownText;if(isPaused){cooldownBtn.classList.add('paused');if(cooldownBtnMobile)cooldownBtnMobile.classList.add('paused')}else{cooldownBtn.classList.remove('paused');if(cooldownBtnMobile)cooldownBtnMobile.classList.remove('paused')}let modeText='🧪 测试';if(d.test_mode===true){modeText='🧪 测试'}else if(d.test_mode===false){modeText='🔴 实盘'}else{modeText='模式未知'}modeBtn.textContent=modeText;if(modeBtnMobile)modeBtnMobile.textContent=modeText;updateAIStatus()}
function checkCooldownDetails(){if(!window.lastSummaryData){alert('正在加载数据，请稍后...');return}const d=window.lastSummaryData;let msg='';if(currentModel==='combined'){const dsStatus=d.models?.deepseek?.cooldown_status;const qwStatus=d.models?.qwen?.cooldown_status;if(!dsStatus&&!qwStatus){msg='系统正常运行中，所有交易功能正常'}else{if(dsStatus?.is_paused){msg+='🤖 DeepSeek: ';msg+=dsStatus.reason||'冷静期';if(dsStatus.pause_until){msg+='\\n恢复时间: '+dsStatus.pause_until}msg+='\\n\\n'}if(qwStatus?.is_paused){msg+='🧠 通义千问: ';msg+=qwStatus.reason||'冷静期';if(qwStatus.pause_until){msg+='\\n恢复时间: '+qwStatus.pause_until}}if(!msg)msg='系统正常运行中'}}else{const status=d.cooldown_status;if(status?.is_paused){msg=status.reason||'当前处于冷静期';if(status.pause_until){msg+='\\n\\n恢复时间: '+status.pause_until}}else{msg='系统正常运行中，交易功能正常'}}alert(msg)}
async function toggleMode(){if(currentModel==='combined'){alert('请先选择单个模型（DeepSeek或通义千问）再切换模式');return}const confirmMsg='确认要切换运行模式吗？\\n\\n注意：切换可能需要几秒钟时间，请耐心等待。';if(!confirm(confirmMsg))return;const modelName=currentModel==='deepseek'?'deepseek':'qwen';try{const response=await fetch('/control-trading-system',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'toggle_mode',model:modelName})});const result=await response.json();if(result.error){alert('切换失败: '+result.error)}else{alert('模式切换成功！\\n当前模式: '+(result.mode||'未知'));setTimeout(()=>refresh(),1000)}}catch(error){alert('切换失败: '+error.message)}}function updatePos(d){if(!d||!d.positions)return;let filteredPositions=d.positions;if(currentModel!=='combined'){filteredPositions=d.positions.filter(p=>p.model===currentModel)}if(chartMode==='price'&&currentSymbol){filteredPositions=filteredPositions.filter(p=>{const sym=p.symbol||'';return sym.includes(currentSymbol)})}if(filteredPositions.length===0){document.getElementById('positionsTable').innerHTML='<div class="no-data">暂无持仓</div>';renderPositions([]);return}const sortedPositions=filteredPositions.slice().sort((a,b)=>{const timeA=a.open_time||'';const timeB=b.open_time||'';return timeB.localeCompare(timeA)});const tradesMap={};if(d.recent_trades){d.recent_trades.forEach(t=>{const coin=(t['币种']||'').split('/')[0].toUpperCase();const direction=t['方向']||'';const key1=`${coin}_${direction}`;const key2=`${t['币种']}_${direction}`;const key3=`${coin}_${direction==='多'?'long':direction==='空'?'short':direction}`;if(!t['平仓时间']||!t['平仓时间'].trim()){const reason=t['开仓理由']||'';tradesMap[key1]=reason;tradesMap[key2]=reason;tradesMap[key3]=reason;}});}sortedPositions.forEach(p=>{const coin=p.symbol.split('/')[0].toUpperCase();const sideText=p.side==='long'||p.side==='多'?'多':'空';const posKey1=`${coin}_${sideText}`;const posKey2=`${p.symbol}_${sideText}`;const posKey3=`${coin}_${p.side}`;p.open_reason=tradesMap[posKey1]||tradesMap[posKey2]||tradesMap[posKey3]||'无决策记录';p.开仓理由=p.open_reason});renderPositions(sortedPositions)}function updateTrades(d){if(!d||!d.recent_trades)return;statusData=d.status||null;const closedTrades=d.recent_trades.filter(t=>t['平仓时间']&&t['平仓时间'].trim()!=='');if(closedTrades.length===0){document.getElementById('tradesTable').innerHTML='<div class="no-data">暂无交易</div>';return}let sortedTrades=closedTrades.slice();sortedTrades.sort((a,b)=>{const timeA=a['平仓时间']||'';const timeB=b['平仓时间']||'';return timeB.localeCompare(timeA)});if(currentModel!=='combined'){sortedTrades=sortedTrades.filter(t=>t.model===currentModel)}if(chartMode==='price'&&currentSymbol){sortedTrades=sortedTrades.filter(t=>{const sym=t.symbol||t['币种']||'';return sym.includes(currentSymbol)})}renderTrades(sortedTrades)}async function updateChart(d){if(chartMode!=='pnl')return;if(!d?.pnl_24h&&!d?.status)return;try{const isMobile=window.innerWidth<=768;const canvas=document.getElementById('pnlChartCanvas');if(!canvas){console.error('找不到 pnlChartCanvas');return}const container=document.getElementById('pnlChart');if(container){container.style.height=isMobile?'200px':'450px'}const ctx=canvas.getContext('2d');if(chart)chart.destroy();if(currentModel==='combined'){let params=new URLSearchParams(currentTimeRange==='all'?{}:{limit:96});if(currentTimeRange!=='all'){params.append('range',currentTimeRange)}else{params.append('range','all')}if(customStartDate&&customEndDate){params.append('start_date',customStartDate);params.append('end_date',customEndDate)}const [dsPnl,qwPnl]=await Promise.all([fetch(`/trading-pnl?${params}&model=deepseek`).then(r=>r.json()),fetch(`/trading-pnl?${params}&model=qwen`).then(r=>r.json())]);let dsAssets=dsPnl.pnl_data?.map(d=>parseFloat(d['总资产']||d['total_assets']||0))||[];let qwAssets=qwPnl.pnl_data?.map(d=>parseFloat(d['总资产']||d['total_assets']||0))||[];const maxLen=Math.max(dsAssets.length,qwAssets.length);if(dsAssets.length<maxLen&&dsAssets.length>0){const lastVal=dsAssets[dsAssets.length-1];while(dsAssets.length<maxLen)dsAssets.push(lastVal)}if(qwAssets.length<maxLen&&qwAssets.length>0){const lastVal=qwAssets[qwAssets.length-1];while(qwAssets.length<maxLen)qwAssets.push(lastVal)}const rawLabels=dsPnl.pnl_data?.map(d=>d['时间']||d['timestamp']||'')||[];const labels=rawLabels.map(time=>{if(!time)return'';const isMultiDay=currentTimeRange==='all'||currentTimeRange==='month'||currentTimeRange==='custom';if(isMultiDay){const parts=time.split(' ');if(parts.length===2){const datePart=parts[0].split('-');return datePart[1]+'-'+datePart[2]}return time.substring(0,10)}else{return time.split(' ')[1]||time}});const combinedAssets=dsAssets.map((ds,i)=>ds+(qwAssets[i]||0));chart=new Chart(ctx,{type:'line',data:{labels,datasets:[{label:'综合总资产',data:combinedAssets,borderColor:'#f0bc3b',backgroundColor:'rgba(240,188,59,0.15)',borderWidth:2,tension:0.3,fill:true,pointRadius:0,pointHoverRadius:isMobile?4:5,pointBackgroundColor:'#f0bc3b',pointBorderColor:'#fff',pointBorderWidth:2},{label:'🤖 DeepSeek',data:dsAssets,borderColor:'#3b82f6',backgroundColor:'rgba(59,130,246,0.05)',borderWidth:1.5,tension:0.3,fill:false,pointRadius:0,pointHoverRadius:isMobile?4:5,hidden:isMobile},{label:'🧠 通义千问',data:qwAssets,borderColor:'#f97316',backgroundColor:'rgba(249,115,22,0.05)',borderWidth:1.5,tension:0.3,fill:false,pointRadius:0,pointHoverRadius:isMobile?4:5,hidden:isMobile}]},options:{responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},plugins:{legend:{display:true,position:'top',labels:{font:{size:isMobile?9:11},padding:isMobile?6:8,usePointStyle:true}},tooltip:{enabled:true,backgroundColor:'rgba(0,0,0,0.85)',titleColor:'#fff',bodyColor:'#fff',borderColor:'#f0bc3b',borderWidth:1,padding:isMobile?8:12,displayColors:true,callbacks:{label:ctx=>ctx.dataset.label+': '+ctx.parsed.y.toFixed(2)+' U',title:ctx=>rawLabels[ctx[0].dataIndex]||ctx[0].label}},zoom:{zoom:{wheel:{enabled:true,speed:0.1},pinch:{enabled:true},mode:'x',onZoomComplete:({chart})=>{chart.update('none')}},pan:{enabled:true,mode:'x',onPanComplete:({chart})=>{chart.update('none')}},limits:{x:{min:'original',max:'original'}}}},scales:{y:{beginAtZero:false,grid:{color:'rgba(0,0,0,0.05)',drawBorder:false},ticks:{callback:v=>v.toFixed(0)+'U',font:{size:isMobile?9:11},color:'#666',maxTicksLimit:isMobile?5:7}},x:{grid:{display:false},ticks:{maxTicksLimit:isMobile?6:12,font:{size:isMobile?9:10},color:'#666',maxRotation:0,minRotation:0,autoSkip:true,autoSkipPadding:10}}}},plugins:[{afterDatasetsDraw:function(chart){const ctx=chart.ctx;const labelY=[];chart.data.datasets.forEach((dataset,i)=>{const meta=chart.getDatasetMeta(i);if(!meta.data.length||meta.hidden)return;const lastPoint=meta.data[meta.data.length-1];const value=dataset.data[dataset.data.length-1];if(!lastPoint||value===null||value===undefined)return;const labelColors=['#f0bc3b','#3b82f6','#f97316'];const color=labelColors[i]||'#f0bc3b';const text=value.toFixed(2)+'U';ctx.font=isMobile?'bold 9px Arial':'bold 11px Arial';const x=lastPoint.x-45;const labelHeight=isMobile?18:22;const labelOffset=isMobile?20:25;let y=Math.max(lastPoint.y-labelOffset,labelHeight/2+5);for(let prevY of labelY){if(Math.abs(y-prevY)<(isMobile?22:26)){y=prevY-(isMobile?24:28)}}labelY.push(y);ctx.save();ctx.shadowColor='rgba(0,0,0,0.35)';ctx.shadowBlur=12;ctx.shadowOffsetX=0;ctx.shadowOffsetY=2;ctx.fillStyle='white';ctx.fillRect(x-40,y-labelHeight/2,80,labelHeight);ctx.strokeStyle='rgba(240,188,59,0.2)';ctx.lineWidth=1.5;ctx.strokeRect(x-40,y-labelHeight/2,80,labelHeight);ctx.restore();ctx.fillStyle=color;ctx.textAlign='center';ctx.textBaseline='middle';ctx.font=isMobile?'bold 9px Arial':'bold 11px Arial';ctx.fillText(text,x,y);ctx.beginPath();ctx.arc(lastPoint.x,lastPoint.y,isMobile?4:5,0,2*Math.PI);ctx.fillStyle=dataset.borderColor;ctx.fill();ctx.strokeStyle='white';ctx.lineWidth=2;ctx.stroke()})}}]})}else{let params=new URLSearchParams(currentTimeRange==='all'?{model:currentModel}:{limit:96,model:currentModel});if(currentTimeRange!=='all'){params.append('range',currentTimeRange)}else{params.append('range','all')}if(customStartDate&&customEndDate){params.append('start_date',customStartDate);params.append('end_date',customEndDate)}const r=await fetch(`/trading-pnl?${params}`),pd=await r.json();if(!pd.pnl_data||pd.pnl_data.length===0)return;const data=pd.pnl_data;const rawLabels=data.map(d=>d['时间']||d['timestamp']||'');const labels=rawLabels.map(time=>{if(!time)return'';const isMultiDay=currentTimeRange==='all'||currentTimeRange==='month'||currentTimeRange==='custom';if(isMultiDay){const parts=time.split(' ');if(parts.length===2){const datePart=parts[0].split('-');return datePart[1]+'-'+datePart[2]}return time.substring(0,10)}else{return time.split(' ')[1]||time}});const assets=data.map(d=>parseFloat(d['总资产']||d['total_assets']||0));const gradient=ctx.createLinearGradient(0,0,0,300);gradient.addColorStop(0,'rgba(240,188,59,0.3)');gradient.addColorStop(1,'rgba(240,188,59,0.05)');chart=new Chart(ctx,{type:'line',data:{labels,datasets:[{label:'总资产',data:assets,borderColor:'#f0bc3b',backgroundColor:gradient,borderWidth:2,tension:0.3,fill:true,pointRadius:0,pointHoverRadius:isMobile?4:5,pointBackgroundColor:'#f0bc3b',pointBorderColor:'#fff',pointBorderWidth:2}]},options:{responsive:true,maintainAspectRatio:false,interaction:{mode:'index',intersect:false},plugins:{legend:{display:!isMobile,position:'top',labels:{font:{size:isMobile?10:12},padding:isMobile?8:10,usePointStyle:true}},tooltip:{enabled:true,backgroundColor:'rgba(0,0,0,0.8)',titleColor:'#fff',bodyColor:'#fff',borderColor:'#f0bc3b',borderWidth:1,padding:isMobile?8:12,displayColors:false,callbacks:{label:ctx=>ctx.parsed.y.toFixed(2)+' U',title:ctx=>rawLabels[ctx[0].dataIndex]||ctx[0].label}},zoom:{zoom:{wheel:{enabled:true,speed:0.1},pinch:{enabled:true},mode:'x',onZoomComplete:({chart})=>{chart.update('none')}},pan:{enabled:true,mode:'x',onPanComplete:({chart})=>{chart.update('none')}},limits:{x:{min:'original',max:'original'}}}},scales:{y:{beginAtZero:false,grid:{color:'rgba(0,0,0,0.05)',drawBorder:false},ticks:{callback:v=>v.toFixed(0)+'U',font:{size:isMobile?9:11},color:'#666',maxTicksLimit:isMobile?5:7}},x:{grid:{display:false},ticks:{maxTicksLimit:isMobile?6:12,font:{size:isMobile?9:10},color:'#666',maxRotation:0,minRotation:0,autoSkip:true,autoSkipPadding:10}}}},plugins:[{afterDatasetsDraw:function(chart){const ctx=chart.ctx;chart.data.datasets.forEach((dataset,i)=>{const meta=chart.getDatasetMeta(i);if(!meta.data.length)return;const lastPoint=meta.data[meta.data.length-1];const value=dataset.data[dataset.data.length-1];if(!lastPoint||value===null||value===undefined)return;const text=value.toFixed(2)+'U';ctx.font=isMobile?'bold 9px Arial':'bold 11px Arial';const x=lastPoint.x-45;const labelHeight=isMobile?18:22;const labelOffset=isMobile?20:25;const y=Math.max(lastPoint.y-labelOffset,labelHeight/2+5);ctx.save();ctx.shadowColor='rgba(0,0,0,0.35)';ctx.shadowBlur=12;ctx.shadowOffsetX=0;ctx.shadowOffsetY=2;ctx.fillStyle='white';ctx.fillRect(x-40,y-labelHeight/2,80,labelHeight);ctx.strokeStyle='rgba(240,188,59,0.2)';ctx.lineWidth=1.5;ctx.strokeRect(x-40,y-labelHeight/2,80,labelHeight);ctx.restore();ctx.fillStyle='#f0bc3b';ctx.textAlign='center';ctx.textBaseline='middle';ctx.font=isMobile?'bold 9px Arial':'bold 11px Arial';ctx.fillText(text,x,y);ctx.beginPath();ctx.arc(lastPoint.x,lastPoint.y,isMobile?4:5,0,2*Math.PI);ctx.fillStyle=dataset.borderColor;ctx.fill();ctx.strokeStyle='white';ctx.lineWidth=2;ctx.stroke()})}}]})}}catch(e){console.error(e)}}function toggleThink(el){const content=el.nextElementSibling;const arrow=el.querySelector('.think-arrow');content.classList.toggle('show');arrow.classList.toggle('open')}async function loadAIDecisions(){try{let allDecisions=[];if(currentModel==='combined'){const [dsRes,qwRes]=await Promise.all([fetch('/trading-ai-decisions?limit=20&model=deepseek').then(r=>r.json()),fetch('/trading-ai-decisions?limit=20&model=qwen').then(r=>r.json())]);const dsDecisions=(dsRes.decisions||[]).map(d=>({...d,model:'🤖 DeepSeek'}));const qwDecisions=(qwRes.decisions||[]).map(d=>({...d,model:'🧠 通义千问'}));allDecisions=[...dsDecisions,...qwDecisions].sort((a,b)=>a.timestamp.localeCompare(b.timestamp))}else{const r=await fetch(`/trading-ai-decisions?limit=20&model=${currentModel}`),d=await r.json();allDecisions=d.decisions||[]}if(allDecisions.length>0){const div=document.getElementById('chatMessages');if(div.querySelector('.loading'))div.innerHTML='';div.innerHTML='';allDecisions.forEach(dec=>{const msg=document.createElement('div');const hasActions=dec.actions&&dec.actions.length>0&&dec.actions.some(a=>{const op=a.operation||a.action;return op&&op!=='HOLD'&&!op.includes('HOLD')});msg.className=hasActions?'message-ai-decision executed':'message-ai-decision';msg.setAttribute('data-ts',dec.timestamp+(dec.model||''));let bjTime=dec.timestamp;if(bjTime){const dt=new Date(bjTime.replace(' ','T'));dt.setHours(dt.getHours()+8);bjTime=dt.toLocaleString('zh-CN',{year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit'}).replace(/\//g,'-')}let thinkProcess=dec['思考过程']||'';if(typeof thinkProcess==='object'){thinkProcess=JSON.stringify(thinkProcess,null,2).replace(/[{}"]/g,'')}let thinkHtml='';if(thinkProcess){thinkHtml=`<div class="think-box"><div class="think-toggle" onclick="toggleThink(this)"><span class="think-title">💭 思考过程</span><span class="think-arrow">▼</span></div><div class="think-content">${thinkProcess}</div></div>`}const modelBadge=dec.model?`<span style="display:inline-block;padding:2px 8px;background:#f0bc3b;border-radius:4px;font-size:10px;font-weight:600;margin-left:8px">${dec.model}</span>`:'';const bgColor=dec.model==='🤖 DeepSeek'?'rgba(59,130,246,0.08)':dec.model==='🧠 通义千问'?'rgba(249,115,22,0.08)':'rgba(240,188,59,0.08)';const borderColor=dec.model==='🤖 DeepSeek'?'#3b82f6':dec.model==='🧠 通义千问'?'#f97316':'#0ea5e9';msg.style.backgroundColor=bgColor;msg.style.borderLeftColor=borderColor;const analysisText=typeof dec.analysis==='object'?JSON.stringify(dec.analysis):(dec.analysis||'无');const riskText=typeof dec.risk_assessment==='object'?JSON.stringify(dec.risk_assessment):(dec.risk_assessment||'无');msg.innerHTML=`<div style="font-size:11px;color:#64748b;margin-bottom:8px">${bjTime}${modelBadge}</div>${thinkHtml}<div class="decision-content"><div class="decision-analysis"><strong>📊 分析：</strong>${analysisText}</div><div class="decision-risk"><strong>⚠️ 风险：</strong>${riskText}</div></div>`;div.appendChild(msg)});div.scrollTop=div.scrollHeight;lastDecisionCount=allDecisions.length}}catch(e){console.error('加载AI决策失败:',e)}}function updateLatestTradeDecision(d){const div=document.getElementById('latestDecision');if(!d||!d.recent_trades||d.recent_trades.length===0){div.innerHTML='<div style="background:#fff3cd;padding:8px;border-radius:6px;border-left:3px solid #ffc107;font-size:13px">⏸️ <strong>当前观望</strong>，等待更好的交易机会</div>';return}let sortedTrades=d.recent_trades.slice().filter(t=>{const openTime=t['开仓时间']||'';const closeTime=t['平仓时间']||'';return openTime.trim()!==''||closeTime.trim()!==''});if(currentModel!=='combined'){sortedTrades=sortedTrades.filter(t=>t.model===currentModel)}if(sortedTrades.length===0){div.innerHTML='<div style="background:#fff3cd;padding:8px;border-radius:6px;border-left:3px solid #ffc107;font-size:13px">⏸️ <strong>当前观望</strong>，等待更好的交易机会</div>';return}sortedTrades.sort((a,b)=>{const timeA=(a['平仓时间']&&a['平仓时间'].trim())?a['平仓时间']:a['开仓时间']||'';const timeB=(b['平仓时间']&&b['平仓时间'].trim())?b['平仓时间']:b['开仓时间']||'';return timeA.localeCompare(timeB)});const latestTrade=sortedTrades[sortedTrades.length-1];if(!latestTrade){div.innerHTML='<div style="background:#fff3cd;padding:8px;border-radius:6px;border-left:3px solid #ffc107;font-size:13px">⏸️ <strong>当前观望</strong>，等待更好的交易机会</div>';return}const isClosed=latestTrade['平仓时间']&&latestTrade['平仓时间'].trim()!=='';const pnl=parseFloat(latestTrade['盈亏(U)']||0);let bgColor,borderColor;if(!isClosed){bgColor='#fff7ed';borderColor='#f97316'}else if(pnl>=0){bgColor='#f0fdf4';borderColor='#10b981'}else{bgColor='#fef2f2';borderColor='#ef4444'}const opType=isClosed?'平仓':'开仓';const opEmoji=isClosed?'🔒':latestTrade['方向']==='多'?'📈':'📉';const opText=isClosed?'平仓':(latestTrade['方向']==='多'?'开多仓':'开空仓');const reason=isClosed?(latestTrade['平仓理由']||''):(latestTrade['开仓理由']||'');const actionTime=isClosed?latestTrade['平仓时间']:latestTrade['开仓时间'];let bjTime='';if(actionTime){const dt=new Date(actionTime.replace(' ','T'));bjTime=dt.toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}).replace(/\//g,'-')}const modelBadge=currentModel==='combined'&&latestTrade.model?`<span style="display:inline-block;padding:2px 6px;background:#e0f9ff;border-radius:4px;font-size:10px;font-weight:600;margin-left:5px">${latestTrade.model==='deepseek'?'🤖 DeepSeek':'🧠 通义千问'}</span>`:'';const actionPrice=isClosed?latestTrade['平仓价格']:latestTrade['开仓价格'];const stopLoss=parseFloat(latestTrade['止损']||0);const takeProfit=parseFloat(latestTrade['止盈']||0);const posSize=parseFloat(latestTrade['仓位(U)']||0);let detailsHtml='';if(!isClosed){detailsHtml=`${posSize?`<div style="margin-top:6px;font-size:12px"><strong>仓位:</strong> ${posSize.toFixed(2)}U</div>`:''}${stopLoss||takeProfit?`<div style="margin-top:4px;font-size:12px">${stopLoss?`<strong>止损:</strong> <span style="color:#ef4444">$${stopLoss.toFixed(2)}</span>`:''} ${takeProfit?`<strong>止盈:</strong> <span style="color:#10b981">$${takeProfit.toFixed(2)}</span>`:''}</div>`:''}`}else{detailsHtml=`<div style="margin-top:6px;font-size:12px"><strong>盈亏:</strong> <span style="color:${pnl>=0?'#10b981':'#ef4444'};font-weight:700">${pnl>=0?'+':''}${pnl.toFixed(2)}U</span></div>`}div.innerHTML=`<div style="font-size:11px;color:#64748b;margin-bottom:8px">🕐 ${bjTime}${modelBadge}</div><div style="background:${bgColor};padding:10px;border-radius:6px;margin-bottom:8px;border-left:3px solid ${borderColor}"><strong>${opEmoji} ${opText}</strong>: ${latestTrade['币种']||''}${actionPrice?` @ $${parseFloat(actionPrice).toFixed(2)}`:''}<br/><span style="font-size:12px;color:#64748b;margin-top:4px;display:block">${reason||'无'}</span>${detailsHtml}</div>`}function updateLatestDecision(decisions){if(!decisions||decisions.length===0)return;const div=document.getElementById('latestDecision');let filteredDecisions=decisions;if(currentModel!=='combined'){filteredDecisions=decisions.filter(d=>{const modelName=d.model?d.model.replace('🤖 ','').replace('🧠 ','').toLowerCase():'';return modelName.includes(currentModel)})}let latestAction=null;for(let i=filteredDecisions.length-1;i>=0;i--){const dec=filteredDecisions[i];const hasActions=dec.actions&&dec.actions.length>0&&dec.actions.some(a=>{const op=a.operation||a.action;return op&&!op.includes('HOLD')&&op!=='HOLD'});if(hasActions){latestAction=dec;break}}if(!latestAction){div.innerHTML='<div style="background:#fff3cd;padding:8px;border-radius:6px;border-left:3px solid #ffc107;font-size:13px">⏸️ <strong>当前观望</strong>，等待更好的交易机会</div>';return}let bjTime=latestAction.timestamp;if(bjTime){bjTime=new Date(bjTime.replace(' ','T')).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}).replace(/\//g,'-')}const modelBadge=latestAction.model?`<span style="display:inline-block;padding:2px 6px;background:#e0f9ff;border-radius:4px;font-size:10px;font-weight:600;margin-left:5px">${latestAction.model}</span>`:'';let actionHtml='';latestAction.actions.forEach(act=>{const op=act.operation||act.action;if(op&&!op.includes('HOLD')&&op!=='HOLD'){const opText=op==='OPEN_LONG'?'📈 开多仓':op==='OPEN_SHORT'?'📉 开空仓':op==='CLOSE'?'🔒 平仓':'📊 '+op;const bgColor=op==='CLOSE'?'#f0fdf4':'#fef2f2';const borderColor=op==='CLOSE'?'#10b981':'#ef4444';const stopLoss=act.stop_loss_price?`$${parseFloat(act.stop_loss_price).toFixed(2)}`:null;const takeProfit=act.take_profit_price?`$${parseFloat(act.take_profit_price).toFixed(2)}`:null;const posSize=act.position_size_usd?`${parseFloat(act.position_size_usd).toFixed(2)}U`:null;actionHtml+=`<div style="background:${bgColor};padding:10px;border-radius:6px;margin-bottom:8px;border-left:3px solid ${borderColor}"><strong>${opText}</strong>: ${act.symbol||''}<br/><span style="font-size:12px;color:#64748b;margin-top:4px;display:block">${act.reason||''}</span>${posSize?`<div style="margin-top:6px;font-size:12px"><strong>仓位:</strong> ${posSize}</div>`:''}${stopLoss||takeProfit?`<div style="margin-top:4px;font-size:12px">${stopLoss?`<strong>止损:</strong> <span style="color:#ef4444">${stopLoss}</span>`:''} ${takeProfit?`<strong>止盈:</strong> <span style="color:#10b981">${takeProfit}</span>`:''}</div>`:''}</div>`}});const thinkProcess=latestAction['思考过程']||'';const thinkHtml=thinkProcess?`<details style="margin-top:10px;padding:8px;background:#f8fafc;border-radius:4px;font-size:12px"><summary style="cursor:pointer;font-weight:600;color:#0ea5e9">💭 查看思考过程</summary><div style="margin-top:8px;white-space:pre-wrap;line-height:1.6;color:#64748b">${typeof thinkProcess==='object'?JSON.stringify(thinkProcess,null,2):thinkProcess}</div></details>`:'';div.innerHTML=`<div style="font-size:11px;color:#64748b;margin-bottom:8px">🕐 ${bjTime}${modelBadge}</div>${actionHtml}${thinkHtml}`}async function refresh(){const d=await load();if(!d)return;window.lastSummaryData=d;updateUI(d);updatePos(d);updateTrades(d);updateLatestTradeDecision(d);if(chartMode==='price'){await loadPriceChart()}else{await updateChart(d)}await loadAIDecisions()}let chatPassword=null;async function verifyPassword(){let attempts=0;const maxAttempts=3;while(attempts<maxAttempts){const pwd=prompt(`🔐 请输入AI对话密码 (${attempts>0?'剩余'+(maxAttempts-attempts)+'次机会':''})`);if(!pwd){return null}const testResp=await fetch('/trading-chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:'test',password:pwd})});const testData=await testResp.json();if(testData.success||!testData.error||!testData.error.includes('密码')){return pwd}attempts++;if(attempts<maxAttempts){alert('❌ 密码错误，请重试！')}else{alert('❌ 密码错误次数过多，请稍后再试');return null}}return null}async function sendMsg(){const input=document.getElementById('chatInput'),msg=input.value.trim();if(!msg)return;if(!chatPassword){chatPassword=await verifyPassword();if(!chatPassword){addMsg('system','❌ 未输入密码或密码验证失败，消息未发送');return}}addMsg('user',msg);input.value='';const btn=document.getElementById('sendBtn');btn.disabled=true;btn.textContent='思考中...';try{const r=await fetch('/trading-chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message:msg,password:chatPassword})});const d=await r.json();if(d.success){addMsg('ai',d.reply)}else{if(d.error.includes('密码')){chatPassword=null;addMsg('system','❌ 密码验证失败，请重新输入')}else{addMsg('ai','❌ '+d.error)}}}catch(e){addMsg('ai','❌ 连接失败：'+e.message)}finally{btn.disabled=false;btn.textContent='发送'}}function sendQuick(q){document.getElementById('chatInput').value=q;sendMsg()}function addMsg(type,text){const div=document.getElementById('chatMessages');const m=document.createElement('div');m.className=`message message-${type}`;const now=new Date();const beijingTime=new Date(now.getTime()+8*60*60*1000);const t=beijingTime.toISOString().substr(11,5);const content=type==='ai'?formatAIReply(text):text;m.innerHTML=`<div class="message-content">${content}</div><div class="message-time">${t}</div>`;div.appendChild(m);div.scrollTop=div.scrollHeight}async function loadVisitorCount(){try{const r=await fetch('/trading-visitor-count');const d=await r.json();document.getElementById('visitorNum').textContent=d.count||0}catch(e){console.error('加载访客数失败:',e)}}function shareToFriends(){const url='https://bitechain.site/';if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(url).then(()=>{alert('✅ 链接已复制！\\n\\n快去分享给好友吧：\\n'+url)}).catch(()=>{fallbackCopy(url)})}else{fallbackCopy(url)}}function fallbackCopy(text){const textarea=document.createElement('textarea');textarea.value=text;textarea.style.position='fixed';textarea.style.opacity='0';document.body.appendChild(textarea);textarea.select();try{document.execCommand('copy');alert('✅ 链接已复制！\\n\\n快去分享给好友吧：\\n'+text)}catch(e){alert('❌ 复制失败，请手动复制：\\n'+text)}document.body.removeChild(textarea)}async function toggleMode(){if(currentModel==='combined'){alert('请先选择具体的模型（DeepSeek或通义千问）再切换模式');return}const pwd=prompt('请输入控制密码:');if(!pwd)return;try{const r=await fetch('/trading-control',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'toggle_mode',password:pwd,model:currentModel})});const d=await r.json();alert(d.message||d.error);refresh()}catch(e){alert('操作失败:'+e)}}document.addEventListener('DOMContentLoaded',()=>{refresh();loadVisitorCount();setInterval(refresh,15000);setInterval(loadVisitorCount,30000)})</script><script charset="UTF-8" id="LA_COLLECT" src="//sdk.51.la/js-sdk-pro.min.js"></script><script>LA.init({id:"3KofEcA7mg3VpMDc",ck:"3KofEcA7mg3VpMDc",autoTrack:true})
let positionsData=[],tradesData=[],statusData=null,currentPositionPage=1,currentTradePage=1;function getPageSize(type){const isMobile=window.innerWidth<=768;if(type==='positions')return isMobile?3:5;return isMobile?5:10}
function renderPositions(positions){positionsData=positions||[];positionsData.sort((a,b)=>{const timeA=a.open_time||'';const timeB=b.open_time||'';return timeB.localeCompare(timeA)});const pageSize=getPageSize('positions');const totalPages=Math.ceil(positionsData.length/pageSize);currentPositionPage=Math.min(currentPositionPage,Math.max(1,totalPages));const start=(currentPositionPage-1)*pageSize;const end=start+pageSize;const pageData=positionsData.slice(start,end);const table=document.getElementById('positionsTable');if(!pageData.length){table.innerHTML='<div class="no-data">暂无持仓</div>';document.getElementById('positionsPagination').style.display='none';return}
const isMobile=window.innerWidth<=768;const showModel=currentModel==='combined';if(isMobile){let html='';pageData.forEach(p=>{const pnl=parseFloat(p.unrealized_pnl||0),c=pnl>=0?'#10b981':'#ef4444';let holdTime='',openTimeStr='';if(p.open_time){const openTime=new Date(p.open_time.replace(' ','T')+'+08:00');openTimeStr=openTime.toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',timeZone:'Asia/Shanghai'}).replace(/\//g,'-');const now=new Date();const diffMs=now-openTime;const diffHours=Math.floor(diffMs/3600000);const diffDays=Math.floor(diffHours/24);const remainHours=diffHours%24;if(diffDays>0){holdTime=`${diffDays}天${remainHours}h`}else if(diffHours>0){holdTime=`${diffHours}h`}else{holdTime='<1h'}}else{openTimeStr='--';holdTime='--'}const entryPrice=parseFloat(p.entry_price||0);const stopLoss=parseFloat(p.stop_loss||0);const takeProfit=parseFloat(p.take_profit||0);const riskReward=parseFloat(p.risk_reward||0);const leverage=parseFloat(p.leverage||1);const margin=parseFloat(p.margin||0);const expectedPnl=parseFloat(p.expected_pnl||0);const openReason=(p.open_reason||p.开仓理由||'无决策记录');const modelBadge=showModel&&p.model?`<span style="display:inline-block;padding:2px 6px;background:${p.model==='deepseek'?'#e0f2fe':'#fed7aa'};color:${p.model==='deepseek'?'#0369a1':'#c2410c'};border-radius:4px;font-size:9px;font-weight:600;margin-left:5px">${p.model==='deepseek'?'🤖DS':'🧠QW'}</span>`:'';const reasonData=encodeURIComponent(JSON.stringify({type:'position',symbol:p.symbol,side:p.side,openReason:openReason,openTime:openTimeStr,holdTime:holdTime,margin:margin.toFixed(2),leverage:leverage.toFixed(1),takeProfit:takeProfit.toFixed(2),stopLoss:stopLoss.toFixed(2)}));html+=`<div class="position-card" data-reason="${reasonData}" onclick="showReasonDialog(this.getAttribute('data-reason'))" style="cursor:pointer"><div class="position-card-header"><span class="symbol">${p.symbol}</span><span class="side">${p.side}${modelBadge}</span></div><div class="position-card-row"><span class="label">开仓时间</span><span class="value">${openTimeStr}</span></div><div class="position-card-row"><span class="label">持仓时长</span><span class="value">${holdTime}</span></div><div class="position-card-row"><span class="label">开仓价</span><span class="value">$${entryPrice.toFixed(2)}</span></div><div class="position-card-row"><span class="label">数量</span><span class="value">${parseFloat(p.size).toFixed(4)}</span></div><div class="position-card-row"><span class="label">保证金</span><span class="value">${margin.toFixed(2)}U</span></div><div class="position-card-row"><span class="label">杠杆率</span><span class="value">${leverage.toFixed(1)}x</span></div><div class="position-card-row"><span class="label">预计止盈价</span><span class="value" style="color:#10b981">$${takeProfit.toFixed(2)}</span></div><div class="position-card-row"><span class="label">预计止损价</span><span class="value" style="color:#ef4444">$${stopLoss.toFixed(2)}</span></div><div class="position-card-row"><span class="label">预计盈亏比</span><span class="value">${riskReward?riskReward.toFixed(2):'--'}</span></div><div class="position-card-row"><span class="label">预期盈亏</span><span class="value" style="color:#10b981">${expectedPnl.toFixed(2)}U</span></div><div class="position-card-row"><span class="label">当前盈亏</span><span class="value" style="color:${c};font-weight:700;font-size:15px">${pnl>=0?'+':''}${pnl.toFixed(2)}U</span></div></div>`});table.innerHTML=html}else{let html=`<table style="font-size:12px"><thead><tr><th>币种</th><th>方向</th>${showModel?'<th>模型</th>':''}<th>开仓时间</th><th>持仓时长</th><th>开仓价</th><th>数量</th><th>保证金</th><th>杠杆率</th><th>预计止盈价</th><th>预计止损价</th><th>预计盈亏比</th><th>预期盈亏</th><th>当前盈亏</th></tr></thead><tbody>`;pageData.forEach(p=>{const pnl=parseFloat(p.unrealized_pnl||0),c=pnl>=0?'profit':'loss';let holdTime='',openTimeStr='';if(p.open_time){const openTime=new Date(p.open_time.replace(' ','T')+'+08:00');openTimeStr=openTime.toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',timeZone:'Asia/Shanghai'}).replace(/\//g,'-');const now=new Date();const diffMs=now-openTime;const diffHours=Math.floor(diffMs/3600000);const diffDays=Math.floor(diffHours/24);const remainHours=diffHours%24;if(diffDays>0){holdTime=`${diffDays}天${remainHours}h`}else if(diffHours>0){holdTime=`${diffHours}h`}else{holdTime='<1h'}}else{openTimeStr='--';holdTime='--'}const entryPrice=parseFloat(p.entry_price||0);const stopLoss=parseFloat(p.stop_loss||0);const takeProfit=parseFloat(p.take_profit||0);const riskReward=parseFloat(p.risk_reward||0);const leverage=parseFloat(p.leverage||1);const margin=parseFloat(p.margin||0);const expectedPnl=parseFloat(p.expected_pnl||0);const openReason=(p.open_reason||p.开仓理由||'无决策记录');const tooltip=`📝 开仓决策:\n${openReason}\n\n📊 详细信息:\n开仓时间: ${openTimeStr}\n持仓时长: ${holdTime}\n保证金: ${margin.toFixed(2)}U\n杠杆率: ${leverage.toFixed(1)}x\n止盈价: $${takeProfit.toFixed(2)}\n止损价: $${stopLoss.toFixed(2)}`;const modelCell=showModel&&p.model?`<td><span style="display:inline-block;padding:2px 6px;background:${p.model==='deepseek'?'#e0f2fe':'#fed7aa'};color:${p.model==='deepseek'?'#0369a1':'#c2410c'};border-radius:4px;font-size:10px;font-weight:600">${p.model==='deepseek'?'🤖DS':'🧠QW'}</span></td>`:'';html+=`<tr title="${tooltip}" style="cursor:pointer"><td><strong>${p.symbol}</strong></td><td>${p.side}</td>${modelCell}<td style="font-size:10px">${openTimeStr}</td><td style="font-size:10px">${holdTime}</td><td>$${entryPrice.toFixed(2)}</td><td>${parseFloat(p.size).toFixed(4)}</td><td>${margin.toFixed(2)}U</td><td>${leverage.toFixed(1)}x</td><td style="color:#10b981">$${takeProfit.toFixed(2)}</td><td style="color:#ef4444">$${stopLoss.toFixed(2)}</td><td>${riskReward?riskReward.toFixed(2):'--'}</td><td style="color:#10b981">${expectedPnl.toFixed(2)}U</td><td class="${c}">${pnl>=0?'+':''}${pnl.toFixed(2)}U</td></tr>`});html+='</tbody></table>';table.innerHTML=html}if(totalPages>1){document.getElementById('positionsPagination').style.display='block';document.getElementById('positionsPageInfo').textContent=`第 ${currentPositionPage}/${totalPages} 页 (共${positionsData.length}条)`;document.querySelector('#positionsPagination button:first-child').disabled=currentPositionPage===1;document.querySelector('#positionsPagination button:last-child').disabled=currentPositionPage===totalPages}else{document.getElementById('positionsPagination').style.display='none'}}
function renderTrades(trades){tradesData=trades||[];tradesData.sort((a,b)=>{const timeA=a['平仓时间']||'';const timeB=b['平仓时间']||'';return timeB.localeCompare(timeA)});const pageSize=getPageSize('trades');const totalPages=Math.ceil(tradesData.length/pageSize);currentTradePage=Math.min(currentTradePage,Math.max(1,totalPages));const start=(currentTradePage-1)*pageSize;const end=start+pageSize;const pageData=tradesData.slice(start,end);const table=document.getElementById('tradesTable');if(!pageData.length){table.innerHTML='<div class="no-data">暂无交易记录</div>';document.getElementById('tradesPagination').style.display='none';return}
const winRate=statusData?.win_rate||0;const winCount=statusData?.win_count||0;const totalTrades=statusData?.total_trades||0;const winRateColor=winRate>=60?'#10b981':winRate>=40?'#f97316':'#ef4444';const winRateHtml=`<div style="background:rgba(240,188,59,0.1);padding:10px;border-radius:6px;margin-bottom:15px;border-left:3px solid ${winRateColor}"><span style="font-size:13px;color:#64748b">📊 交易胜率：</span><span style="font-size:16px;font-weight:700;color:${winRateColor};margin-left:5px">${winRate.toFixed(1)}%</span><span style="font-size:12px;color:#94a3b8;margin-left:10px">(${winCount}胜/${totalTrades}笔)</span></div>`;
const isMobile=window.innerWidth<=768;const showModel=currentModel==='combined';if(isMobile){let html=winRateHtml;pageData.forEach(t=>{const pnl=parseFloat(t['盈亏(U)']||0);const c=pnl>=0?'#10b981':'#ef4444';const posSize=parseFloat(t['仓位(U)']||0);const leverage=parseInt(t['杠杆率']||1);const notionalValue=posSize*leverage;let openTimeStr='',closeTimeStr='',holdTime='';if(t['开仓时间']){const dt=new Date(t['开仓时间'].replace(' ','T'));openTimeStr=dt.toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}).replace(/\//g,'-');}if(t['平仓时间']){const dt=new Date(t['平仓时间'].replace(' ','T'));closeTimeStr=dt.toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}).replace(/\//g,'-');if(t['开仓时间']){const open=new Date(t['开仓时间'].replace(' ','T'));const close=new Date(t['平仓时间'].replace(' ','T'));const diffMs=close-open;const diffHours=Math.floor(diffMs/3600000);const diffDays=Math.floor(diffHours/24);const remainHours=diffHours%24;if(diffDays>0){holdTime=`${diffDays}天${remainHours}h`}else if(diffHours>0){holdTime=`${diffHours}h`}else{const diffMins=Math.floor(diffMs/60000);holdTime=`${diffMins}min`}}}const openPrice=parseFloat(t['开仓价格']||0);const closePrice=parseFloat(t['平仓价格']||0);const openReason=t['开仓理由']||'';const closeReason=t['平仓理由']||'';const modelBadge=showModel&&t.model?`<span style="display:inline-block;padding:2px 6px;background:${t.model==='deepseek'?'#e0f2fe':'#fed7aa'};color:${t.model==='deepseek'?'#0369a1':'#c2410c'};border-radius:4px;font-size:9px;font-weight:600;margin-left:5px">${t.model==='deepseek'?'🤖DS':'🧠QW'}</span>`:'';const reasonData=encodeURIComponent(JSON.stringify({type:'trade',symbol:t['币种']||'',side:t['方向']||'',openReason:openReason,closeReason:closeReason,openTime:openTimeStr,closeTime:closeTimeStr,holdTime:holdTime,posSize:posSize.toFixed(2),leverage:leverage,notionalValue:notionalValue.toFixed(2)}));html+=`<div class="trade-card" data-reason="${reasonData}" onclick="showReasonDialog(this.getAttribute('data-reason'))" style="cursor:pointer"><div class="trade-card-header"><span class="symbol">${t['币种']||'--'}</span><span class="side">${t['方向']||'--'}${modelBadge}</span></div><div class="trade-card-row"><span class="label">开仓时间</span><span class="value">${openTimeStr||'--'}</span></div><div class="trade-card-row"><span class="label">平仓时间</span><span class="value">${closeTimeStr||'--'}</span></div><div class="trade-card-row"><span class="label">持仓时长</span><span class="value">${holdTime||'--'}</span></div><div class="trade-card-row"><span class="label">保证金</span><span class="value">${posSize.toFixed(2)}U</span></div><div class="trade-card-row"><span class="label">杠杆率</span><span class="value">${leverage}x</span></div><div class="trade-card-row"><span class="label">持仓价值</span><span class="value">${notionalValue.toFixed(2)}U</span></div><div class="trade-card-row"><span class="label">开仓价</span><span class="value">$${openPrice.toFixed(2)}</span></div><div class="trade-card-row"><span class="label">平仓价</span><span class="value">${closePrice?'$'+closePrice.toFixed(2):'--'}</span></div><div class="trade-card-row"><span class="label">盈亏</span><span class="value" style="color:${c};font-weight:700;font-size:15px">${pnl?((pnl>=0?'+':'')+pnl.toFixed(2)+'U'):'--'}</span></div></div>`});table.innerHTML=html}else{let html=winRateHtml+`<table style="font-size:11px"><thead><tr><th>币种</th><th>方向</th>${showModel?'<th>模型</th>':''}<th>开仓时间</th><th>平仓时间</th><th>持仓时长</th><th>保证金</th><th>杠杆率</th><th>持仓价值</th><th>开仓价</th><th>平仓价</th><th>盈亏</th></tr></thead><tbody>`;pageData.forEach(t=>{const pnl=parseFloat(t['盈亏(U)']||0);const c=pnl>=0?'profit':'loss';const posSize=parseFloat(t['仓位(U)']||0);const leverage=parseInt(t['杠杆率']||1);const notionalValue=posSize*leverage;let openTimeStr='',closeTimeStr='',holdTime='';if(t['开仓时间']){const dt=new Date(t['开仓时间'].replace(' ','T'));openTimeStr=dt.toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}).replace(/\//g,'-');}if(t['平仓时间']){const dt=new Date(t['平仓时间'].replace(' ','T'));closeTimeStr=dt.toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}).replace(/\//g,'-');if(t['开仓时间']){const open=new Date(t['开仓时间'].replace(' ','T'));const close=new Date(t['平仓时间'].replace(' ','T'));const diffMs=close-open;const diffHours=Math.floor(diffMs/3600000);const diffDays=Math.floor(diffHours/24);const remainHours=diffHours%24;if(diffDays>0){holdTime=`${diffDays}天${remainHours}h`}else if(diffHours>0){holdTime=`${diffHours}h`}else{const diffMins=Math.floor(diffMs/60000);holdTime=`${diffMins}min`}}}const openPrice=parseFloat(t['开仓价格']||0);const closePrice=parseFloat(t['平仓价格']||0);const openReason=t['开仓理由']||'';const closeReason=t['平仓理由']||'';const tooltip=`📝 开仓决策:\n${openReason}\n\n🔒 平仓决策:\n${closeReason||'无'}\n\n📊 详细信息:\n保证金: ${posSize.toFixed(2)}U\n杠杆率: ${leverage}x\n持仓价值: ${notionalValue.toFixed(2)}U\n持仓时长: ${holdTime||'--'}`;const modelCell=showModel&&t.model?`<td><span style="display:inline-block;padding:2px 6px;background:${t.model==='deepseek'?'#e0f2fe':'#fed7aa'};color:${t.model==='deepseek'?'#0369a1':'#c2410c'};border-radius:4px;font-size:10px;font-weight:600">${t.model==='deepseek'?'🤖DS':'🧠QW'}</span></td>`:'';html+=`<tr title="${tooltip}" style="cursor:pointer"><td><strong>${t['币种']||''}</strong></td><td>${t['方向']||''}</td>${modelCell}<td style="font-size:10px">${openTimeStr||'--'}</td><td style="font-size:10px">${closeTimeStr||'--'}</td><td style="font-size:10px">${holdTime||'--'}</td><td>${posSize.toFixed(2)}U</td><td>${leverage}x</td><td><strong>${notionalValue.toFixed(2)}U</strong></td><td>$${openPrice.toFixed(2)}</td><td>$${closePrice?closePrice.toFixed(2):'--'}</td><td class="${c}">${pnl?((pnl>=0?'+':'')+pnl.toFixed(2)+'U'):'--'}</td></tr>`});html+='</tbody></table>';table.innerHTML=html}if(totalPages>1){document.getElementById('tradesPagination').style.display='block';document.getElementById('tradesPageInfo').textContent=`第 ${currentTradePage}/${totalPages} 页 (共${tradesData.length}条)`;document.querySelector('#tradesPagination button:first-child').disabled=currentTradePage===1;document.querySelector('#tradesPagination button:last-child').disabled=currentTradePage===totalPages}else{document.getElementById('tradesPagination').style.display='none'}}
function changePositionPage(delta){const pageSize=getPageSize('positions');const totalPages=Math.ceil(positionsData.length/pageSize);const newPage=currentPositionPage+delta;if(newPage>=1&&newPage<=totalPages){currentPositionPage=newPage;renderPositions(positionsData)}}
function changeTradePage(delta){const pageSize=getPageSize('trades');const totalPages=Math.ceil(tradesData.length/pageSize);const newPage=currentTradePage+delta;if(newPage>=1&&newPage<=totalPages){currentTradePage=newPage;renderTrades(tradesData)}}
const originalFetch=window.fetch;window.fetch=function(...args){return originalFetch.apply(this,args).then(response=>{const url=args[0];if(response.ok&&(url.includes('/trading-summary')||url.includes('/trading-combined'))){return response.clone().json().then(data=>{window.lastSummaryData=data;statusData=data.status||null;return response})}return response})}
window.addEventListener('resize',()=>{if(positionsData.length)renderPositions(positionsData);if(tradesData.length)renderTrades(tradesData)});

async function refresh(){const d=await load();if(!d)return;window.lastSummaryData=d;updateUI(d);updatePos(d);updateTrades(d);updateLatestTradeDecision(d);if(chartMode==='price'){await loadPriceChart()}else{await updateChart(d)}await loadAIDecisions()}
async function loadVisitorCount(){try{const r=await fetch('/trading-visitor-count');const d=await r.json();document.getElementById('visitorNum').textContent=d.count||0}catch(e){console.error('加载访客数失败:',e)}}
function showReasonDialog(encodedData){const data=JSON.parse(decodeURIComponent(encodedData));const dialog=document.getElementById('reasonDialog');const title=document.getElementById('dialogTitle');const content=document.getElementById('dialogContent');const isMobile=window.innerWidth<=768;const titleSize=isMobile?'14px':'16px';const textSize=isMobile?'11px':'14px';const labelSize=isMobile?'10px':'13px';const padding=isMobile?'10px':'15px';if(data.type==='position'){title.textContent=`${data.symbol} ${data.side} - 持仓决策`;content.innerHTML=`<div style="background:#f0f9ff;padding:${padding};border-radius:8px;margin-bottom:${padding};border-left:3px solid #0ea5e9"><h4 style="margin:0 0 8px 0;color:#0369a1;font-size:${titleSize}">📝 开仓决策</h4><p style="margin:0;white-space:pre-wrap;font-size:${textSize};line-height:1.6">${data.openReason}</p></div><div style="background:#f8fafc;padding:${padding};border-radius:8px;border-left:3px solid #64748b"><h4 style="margin:0 0 8px 0;color:#475569;font-size:${titleSize}">📊 详细信息</h4><div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:${labelSize}"><div><span style="color:#64748b;font-size:${labelSize}">开仓时间:</span><br/><strong style="font-size:${textSize}">${data.openTime}</strong></div><div><span style="color:#64748b;font-size:${labelSize}">持仓时长:</span><br/><strong style="font-size:${textSize}">${data.holdTime}</strong></div><div><span style="color:#64748b;font-size:${labelSize}">保证金:</span><br/><strong style="font-size:${textSize}">${data.margin}U</strong></div><div><span style="color:#64748b;font-size:${labelSize}">杠杆率:</span><br/><strong style="font-size:${textSize}">${data.leverage}x</strong></div><div><span style="color:#64748b;font-size:${labelSize}">止盈价:</span><br/><strong style="color:#10b981;font-size:${textSize}">$${data.takeProfit}</strong></div><div><span style="color:#64748b;font-size:${labelSize}">止损价:</span><br/><strong style="color:#ef4444;font-size:${textSize}">$${data.stopLoss}</strong></div></div></div>`}else if(data.type==='trade'){title.textContent=`${data.symbol} ${data.side} - 交易决策`;content.innerHTML=`<div style="background:#f0f9ff;padding:${padding};border-radius:8px;margin-bottom:${padding};border-left:3px solid #0ea5e9"><h4 style="margin:0 0 8px 0;color:#0369a1;font-size:${titleSize}">📝 开仓决策</h4><p style="margin:0;white-space:pre-wrap;font-size:${textSize};line-height:1.6">${data.openReason||'无'}</p></div><div style="background:#fff7ed;padding:${padding};border-radius:8px;margin-bottom:${padding};border-left:3px solid #f97316"><h4 style="margin:0 0 8px 0;color:#c2410c;font-size:${titleSize}">🔒 平仓决策</h4><p style="margin:0;white-space:pre-wrap;font-size:${textSize};line-height:1.6">${data.closeReason||'无'}</p></div><div style="background:#f8fafc;padding:${padding};border-radius:8px;border-left:3px solid #64748b"><h4 style="margin:0 0 8px 0;color:#475569;font-size:${titleSize}">📊 详细信息</h4><div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:${labelSize}"><div><span style="color:#64748b;font-size:${labelSize}">开仓时间:</span><br/><strong style="font-size:${textSize}">${data.openTime}</strong></div><div><span style="color:#64748b;font-size:${labelSize}">平仓时间:</span><br/><strong style="font-size:${textSize}">${data.closeTime}</strong></div><div><span style="color:#64748b;font-size:${labelSize}">持仓时长:</span><br/><strong style="font-size:${textSize}">${data.holdTime}</strong></div><div><span style="color:#64748b;font-size:${labelSize}">保证金:</span><br/><strong style="font-size:${textSize}">${data.posSize}U</strong></div><div><span style="color:#64748b;font-size:${labelSize}">杠杆率:</span><br/><strong style="font-size:${textSize}">${data.leverage}x</strong></div><div><span style="color:#64748b;font-size:${labelSize}">持仓价值:</span><br/><strong style="font-size:${textSize}">${data.notionalValue}U</strong></div></div></div>`}dialog.style.display='flex';document.body.style.overflow='hidden'}
function closeReasonDialog(event){if(!event||event.target.id==='reasonDialog'||event.target.tagName==='BUTTON'){document.getElementById('reasonDialog').style.display='none';document.body.style.overflow='auto'}}
window.onerror=function(msg,url,line,col,error){if(msg==='Script error.')return true;console.error('全局错误:',msg,'at',line+':'+col,error);return true};
document.addEventListener('DOMContentLoaded',()=>{console.log('页面加载完成');try{refresh();console.log('refresh调用成功')}catch(e){console.error('refresh错误:',e);alert('refresh错误: '+e.message)}try{loadVisitorCount();console.log('loadVisitorCount调用成功')}catch(e){console.error('loadVisitorCount错误:',e)}setInterval(refresh,15000);setInterval(loadVisitorCount,30000)})
</script><style>@media(max-width:768px){#dialogTitle{font-size:13px !important}#reasonDialog>div{padding:15px !important;max-width:95% !important}#reasonDialog button{font-size:20px !important}}</style><div id="reasonDialog" style="display:none;position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.5);z-index:10000;align-items:center;justify-content:center" onclick="closeReasonDialog(event)"><div style="background:white;border-radius:12px;max-width:90%;max-height:80vh;overflow-y:auto;padding:20px;box-shadow:0 4px 20px rgba(0,0,0,0.3);position:relative" onclick="event.stopPropagation()"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:15px;border-bottom:2px solid #f0bc3b;padding-bottom:10px"><h3 id="dialogTitle" style="margin:0;color:#2d1b00;font-size:18px">决策详情</h3><button onclick="closeReasonDialog()" style="background:none;border:none;font-size:24px;cursor:pointer;color:#666;padding:0;width:30px;height:30px;display:flex;align-items:center;justify-content:center">×</button></div><div id="dialogContent" style="line-height:1.8;color:#333"></div></div></div></body></html>'''


if __name__ == '__main__':
    # 生产环境配置
    app.config['ENV'] = 'production'
    app.config['DEBUG'] = False
    app.run(host='0.0.0.0', port=5001)
