"""集中导入全部 ORM 模型，供 create_all / Alembic 使用。"""

from app.domains.account.models import AccountGrant, RiskEvent, XyAccount, XyAccountCredential  # noqa: F401
from app.domains.system.models import AuditLog, User  # noqa: F401
from app.notify.models import NotificationChannel  # noqa: F401
