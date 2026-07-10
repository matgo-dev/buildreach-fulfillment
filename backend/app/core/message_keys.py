"""系统消息 key 全集 — 前端翻译文件必须覆盖所有 key。

命名规范:error.<module>.<specific_error>
"""


class MessageKey:
    # auth
    INVALID_CREDENTIALS = "error.auth.invalid_credentials"
    ACCOUNT_LOCKED = "error.auth.account_locked"
    PERMISSION_DENIED = "error.auth.permission_denied"
    NOT_AUTHENTICATED = "error.auth.not_authenticated"

    ACCOUNT_DISABLED = "error.auth.account_disabled"
    PASSWORD_CHANGE_REQUIRED = "error.auth.password_change_required"

    # validation
    VALIDATION_FAILED = "error.validation.failed"

    # general
    NOT_FOUND = "error.general.not_found"
    INTERNAL_ERROR = "error.general.internal_error"
    CONFLICT = "error.general.conflict"

    # general — 兜底处理器
    CLIENT_ERROR = "error.general.client_error"

    # sku
    SPEC_CONTRACT = "error.sku.spec_contract"
