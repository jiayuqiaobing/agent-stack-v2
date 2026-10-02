"""项目类型模板注册表。模板只描述需要覆盖的维度，不直接执行工具。"""

TEMPLATES = {
    "web": {
        "label": "网页项目",
        "triggers": ("网页", "网站", "页面", "聊天界面", "后台界面"),
        "required_sections": ("页面结构", "状态模型", "交互", "响应式", "验收", "发布边界"),
        "checks": (
            "页面结构和页面之间的进入顺序",
            "空状态、错误状态和重复操作",
            "桌面端、窄屏和浏览器兼容",
            "可执行的视觉与功能验收",
        ),
        "capabilities": ("browser_acceptance", "responsive", "accessibility", "visual_acceptance"),
    },
    "web_game": {
        "label": "网页游戏",
        "triggers": ("扫雷", "俄罗斯方块", "贪吃蛇", "网页游戏", "游戏网页"),
        "required_sections": ("页面结构", "坐标约定", "状态机", "数据不变量", "规则常量", "输入", "移动端", "验收", "浏览器实测", "压力测试"),
        "checks": (
            "明确坐标原点、数组下标、可见区、隐藏区和边界方向",
            "playing、paused、gameOver、clearing 等状态",
            "棋盘/实体/计分/计时器数据结构",
            "所有循环有终止条件，所有实体有合法坐标不变量",
            "标准规则附具体数据表、常量或来源，不用‘按标准’代替",
            "输入映射、重复输入、边界碰撞和结束后操作",
            "动画时序、音效限制、失焦暂停和移动端触控",
            "真实浏览器打开、交互、窄屏、失焦和十分钟压力测试",
        ),
        "capabilities": ("browser_acceptance", "responsive", "state_machine", "invariants", "stress_test"),
    },
    "crawler": {
        "label": "爬取与数据工具",
        "triggers": ("爬取", "爬虫", "课表", "抓取", "采集"),
        "required_sections": ("授权", "数据来源", "字段映射", "失败重试", "隐私", "验收"),
        "checks": ("登录/授权和反爬边界", "数据变化与重复数据", "敏感信息和失败恢复"),
        "capabilities": ("authorization", "privacy", "source_validity", "retry_policy"),
    },
    "timetable": {
        "label": "课表导入软件",
        "triggers": ("课表软件", "课表", "课程表", "大学课表"),
        "required_sections": ("授权", "导入方式", "字段映射", "学期周次", "冲突处理", "隐私", "验收"),
        "checks": (
            "学校官网登录/授权和禁止绕过的限制",
            "HTML、图片、PDF、接口或人工导入的来源差异",
            "课程、教师、教室、周次、节次和单双周字段映射",
            "重复课程、调课、跨周和时间冲突处理",
            "隐私数据不上传、不记录密码、失败后可重试",
        ),
        "capabilities": ("authorization", "privacy", "source_validity", "retry_policy"),
    },
    "software": {
        "label": "软件项目",
        "triggers": ("软件", "工具", "桌面应用", "客户端", "应用程序"),
        "required_sections": ("模块", "状态", "权限", "配置", "错误恢复", "发布", "验收"),
        "checks": ("模块职责和数据流", "安装/配置/升级", "崩溃恢复与系统兼容"),
        "capabilities": ("module_boundaries", "permissions", "configuration", "crash_recovery"),
    },
}

UNMATCHED = {
    "label": "未匹配",
    "triggers": (),
    "required_sections": (),
    "checks": (),
    "capabilities": (),
}


def classify(text: str) -> str:
    value = text or ""
    if any(word in value for word in ("课表软件", "课程表软件", "大学课表软件")):
        return "timetable"
    for name in ("web_game", "crawler", "web", "software"):
        if any(trigger in value for trigger in TEMPLATES[name]["triggers"]):
            return name
    return "unmatched"


def template_for(text: str) -> dict:
    name = classify(text)
    result = dict(TEMPLATES[name]) if name in TEMPLATES else dict(UNMATCHED)
    result["name"] = name
    return result
