from models import AuditLog


async def audit(session, user_id: int | None, action: str, detail: str = "") -> None:
    session.add(AuditLog(user_id=user_id, action=action, detail=detail[:500]))
