"""Rules derived from the supplied JD, Kuaishou and Douyin SMS examples."""

CODE = r"(?P<code>[A-Za-z0-9]{4,8})(?![A-Za-z0-9_-])"
SEPARATOR = r"\s*(?:(?:是|为)\s*)?[:：]?\s*"
QUALIFIER = r"\s*(?:[（(]\s*区分大小写\s*[）)]\s*)?"

PLATFORM_ROUTES = {
    "jd_archive_password": {
        "required_keywords": ["【京东】", "以taskid-", "开头的加密导出文件", "密码"],
        "otp_regex": r"密码" + QUALIFIER + SEPARATOR + CODE,
    },
    "kuaishou_export_otp": {
        "required_keywords": ["【快手小店】", "验证码", "正申请导出订单"],
        "otp_regex": r"验证码" + SEPARATOR + CODE,
    },
    "kuaishou_extract_code": {
        "required_keywords": ["【快手小店】", "提取码", "正申请文件提取码"],
        "otp_regex": r"提取码" + SEPARATOR + CODE,
    },
    "douyin_order_otp": {
        "required_keywords": ["【抖店】", "验证码"],
        "otp_regex": r"验证码" + SEPARATOR + CODE,
    },
    "douyin_archive_password": {
        "required_keywords": ["【抖音商城】", "订单导出文件已加密", "解压密码"],
        "otp_regex": r"解压密码" + SEPARATOR + CODE,
    },
}

# Java/Android and Python compatible syntax; match the whole SMS, including newlines.
# Do not rewrite the SMS: backend routing needs the platform, purpose and JD task ID.
_MOBILE_CONTEXTS = {
    "jd_archive_password": (
        r"【京东】\s*以taskid-[0-9]+-开头的加密导出文件[，,]\s*", ""
    ),
    "kuaishou_export_otp": (r"【快手小店】\s*", r"(?=.*正申请导出订单)"),
    "kuaishou_extract_code": (r"【快手小店】\s*", r"(?=.*正申请文件提取码)"),
    "douyin_order_otp": (r"【抖店】\s*", ""),
    "douyin_archive_password": (
        r"【抖音商城】\s*订单导出文件已加密[，,]\s*", ""
    ),
}
MOBILE_MATCH_REGEX = (
    r"(?s)^.*(?:"
    + "|".join(
        prefix + PLATFORM_ROUTES[route_id]["otp_regex"].replace("(?P<code>", "(?:") + suffix
        for route_id, (prefix, suffix) in _MOBILE_CONTEXTS.items()
    )
    + r").*$"
)
