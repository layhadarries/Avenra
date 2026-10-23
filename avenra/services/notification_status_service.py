"""Scoped callers use this read model; it contains no recipient or provider data."""
from datetime import datetime,timezone
from avenra.repositories.notification_outbox_repository import NotificationOutboxRepository
class NotificationStatusService:
    def __init__(self,connection):self.repo=NotificationOutboxRepository(connection)
    def for_alert(self,alert_id):
        summary=self.repo.summary(alert_id)
        count=self.repo.conn.execute("SELECT COUNT(*) FROM push_acknowledgements p JOIN notification_outbox n ON n.id=p.job_id WHERE n.alert_id=? AND p.acknowledged_at IS NOT NULL",(alert_id,)).fetchone()[0]
        summary['contact_acknowledged']=count
        return summary
    @staticmethod
    def timing(client_ts,created_at):
        def parse(value):
            if not isinstance(value,str) or len(value)>64:return None
            try:
                dt=datetime.fromisoformat(value.replace('Z','+00:00'))
                return dt.astimezone(timezone.utc) if dt.tzinfo is not None and dt.utcoffset() is not None else None
            except (ValueError,OverflowError):return None
        pressed,received=parse(client_ts),parse(created_at)
        seconds=(received-pressed).total_seconds() if pressed and received else None
        return {'delay_seconds':int(seconds) if seconds is not None and seconds>=0 else None,
                'device_clock_ahead':seconds is not None and seconds<0,
                'device_time_unverified':True}
