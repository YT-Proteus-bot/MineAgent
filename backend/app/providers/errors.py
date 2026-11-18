"""Provider 层的统一异常。

这些异常的信息会被直接展示给用户，所以 message 必须写成「可照做」的形式：
- ProviderUnavailable  → 缺 Python 库，附上 pip 安装命令
- ProviderConfigError  → 配置项缺失 / 非法，说明缺哪一项
- ProviderCallError    → 远端调用失败，带上 HTTP 状态与响应片段
"""
from __future__ import annotations


class ProviderError(Exception):
    """Provider 层所有异常的基类。"""

    def __init__(self, message: str, *, hint: str = "") -> None:
        self.message = message
        self.hint = hint
        super().__init__(message)

    def to_dict(self) -> dict:
        return {"error": self.__class__.__name__, "message": self.message,
                "hint": self.hint}


class ProviderUnavailable(ProviderError):
    """运行环境缺少该 provider 需要的 Python 库。"""

    def __init__(self, module: str, pip_name: str = "", *, extra: str = "") -> None:
        pkg = pip_name or module
        command = f"pip install {pkg}" + (f" {extra}" if extra else "")
        super().__init__(
            f"使用该功能需要安装 {pkg}",
            hint=f"运行：{command}",
        )
        self.module = module
        self.pip_name = pkg
        self.install_command = command


class ProviderConfigError(ProviderError):
    """配置缺失或非法。"""


class ProviderCallError(ProviderError):
    """远端服务调用失败。"""

    def __init__(self, message: str, *, status: int | None = None,
                 detail: str = "", hint: str = "") -> None:
        text = message
        if status is not None:
            text = f"{text}（HTTP {status}）"
        if detail:
            text = f"{text}：{detail[:300]}"
        super().__init__(text, hint=hint)
        self.status = status
        self.detail = detail
