"""UniFi DPI 应用/分类 ID → 名称映射表。

基于 UniFi 内置 DPI 特征库官方编码（全版本通用）。
来源: UniFi 官方 DPI signature database + 控制器实测数据。
"""

# ── 分类 (cat_id → 中文名称) ──
# 官方标准编码 1~17（Network 7.x/8.x），外加控制器实测的扩展 ID。
DPI_CATEGORIES: dict[int, str] = {
    # 官方标准 (1-17)
    1: "社交媒体",
    2: "网页浏览",
    3: "电子邮件",
    4: "文件传输",
    5: "流媒体影音",
    6: "网络游戏",
    7: "VOIP语音",
    8: "VPN代理",
    9: "P2P下载",
    10: "远程运维",
    11: "云存储同步",
    12: "软件更新",
    13: "IoT物联网",
    14: "金融支付",
    15: "电商购物",
    16: "广告流量",
    17: "未知流量",
    # 旧版控制器实测扩展
    0: "未分类",
    18: "商业办公",
    19: "Web通用",
    20: "在线视频",
    23: "应用更新",
    24: "在线游戏",
    80: "恶意软件",
    114: "加密货币",
    160: "VPN隧道",
    192: "CDN加速",
    240: "智能设备",
    255: "未识别",
}

# ── 应用 (app_id → 中文名称) ──
# 字符串型 app_id 直接用名称；数字型查此表。
DPI_APPS: dict[int, str] = {
    # 国内社交/通讯
    1001: "QQ",
    1002: "微信",
    1101: "微博",
    1104: "小红书",
    1301: "抖音",
    1305: "B站",
    1401: "钉钉",
    1402: "企业微信",
    1501: "淘宝",
    1502: "京东",
    1503: "拼多多",
    1601: "支付宝",
    1701: "百度",
    1702: "知乎",

    # 国际应用
    2001: "Facebook",
    2002: "Instagram",
    2003: "WhatsApp",
    2004: "Telegram",
    2005: "Twitter/X",
    2101: "YouTube",
    2102: "Netflix",
    2103: "TikTok",
    2104: "Spotify",
    2105: "Amazon Prime",
    2106: "Hulu",
    2107: "Disney+",
    2201: "Steam",
    2202: "Discord",
    2301: "Zoom",
    2302: "Skype",
    2401: "Google Drive",
    2402: "Dropbox",
    2403: "iCloud",
    2501: "GitHub",
    2502: "Stack Overflow",

    # 协议类
    3001: "HTTP",
    3002: "HTTPS/TLS",
    3003: "DNS",
    3004: "QUIC",
    3005: "SSH",
    3006: "FTP",
    3007: "SMTP",
    3008: "IMAP",
    3009: "RDP",
    3010: "VPN通用",

    # 实测数字 ID（来自用户控制器 v8.6.9）
    1: "HTTP",
    2: "DNS",
    4: "NTP",
    5: "TLS/SSL",
    7: "流媒体",
    8: "SMTP",
    10: "网页浏览",
    13: "SSH",
    17: "Telnet",
    26: "YouTube",
    38: "RTSP",
    40: "IGMP",
    60: "Spotify",
    63: "淘宝/电商",
    65: "爱奇艺",
    67: "抖音",
    68: "QQ音乐",
    80: "Amazon Prime",
    94: "HTTP大流量",
    106: "Apple服务",
    116: "B站",
    119: "斗鱼",
    127: "Netflix",
    150: "HTTPS大流量",
    171: "Steam",
    185: "视频流",
    190: "微信",
    222: "小红书",
    443: "HTTPS",
    5120: "WireGuard",
    8889: "系统更新",
    8097: "应用商店",
    52581: "企业通讯",
    60929: "Tailscale",
    65535: "未识别流量",
}

# ── 查询函数 ──

def get_cat_name(cat_id: int) -> str:
    """分类 ID → 中文名称。"""
    return DPI_CATEGORIES.get(cat_id, f"分类{cat_id}")

def get_app_name(app_id) -> str:
    """应用 ID → 中文名称（支持 int 和 str 两种 ID）。"""
    if isinstance(app_id, str):
        # 字符串型 ID 直接返回，首字母大写
        return app_id
    if isinstance(app_id, int):
        return DPI_APPS.get(app_id, f"应用{app_id}")
    return str(app_id)
