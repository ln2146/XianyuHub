"""闲鱼适配层异常体系。业务层只需要关心这些类型，而不需要理解 mtop 返回码。"""


class GoofishError(Exception):
    """所有闲鱼交互异常的基类。"""

    def __init__(self, message: str, *, ret: list[str] | None = None, api: str | None = None) -> None:
        super().__init__(message)
        self.ret = ret or []
        self.api = api


class TokenExpiredError(GoofishError):
    """_m_h5_tk 过期 / 缺失：可通过合并 Set-Cookie 后重签名自动恢复。"""


class SessionExpiredError(GoofishError):
    """登录态失效：需要续期或重新扫码。"""


class RiskControlError(GoofishError):
    """触发平台风控（滑块 / 身份验证 / 限流页）。必须熔断并交给人工处理，不做自动破解。"""

    def __init__(self, message: str, *, punish_url: str | None = None, **kw) -> None:
        super().__init__(message, **kw)
        self.punish_url = punish_url


class RateLimitedError(GoofishError):
    """平台提示请求过于频繁。"""


class BizError(GoofishError):
    """业务失败（商品不存在、状态不允许等），直接返回业务层。"""


class VerificationRequiredError(BizError):
    """闲鱼要求本人在 App 里完成身份认证（实名 / 刷脸）后才能继续，verify_url 为手机扫码打开的认证页。"""

    def __init__(self, message: str, *, verify_url: str, **kw) -> None:
        super().__init__(message, **kw)
        self.verify_url = verify_url


class NetworkError(GoofishError):
    """网络层失败（超时、连接错误、非 JSON 响应）。"""


class RiskBlockedError(GoofishError):
    """本地风控守卫拒绝执行（熔断中 / 冷却中 / 需要登录）。不会对外发出请求。"""

    def __init__(self, message: str, *, state: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.state = state
        self.retry_after = retry_after


class ChannelUnavailableError(GoofishError):
    """所选通道不支持该能力或未启用。"""
