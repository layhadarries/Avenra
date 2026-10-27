"""Read Supabase backup metadata and emit a content-free recovery evidence summary.

Uses only the backups GET endpoint. Credentials come from the environment; a
private Management API JSON export can also be inspected without network access.
Backup availability does not establish a successful restore or measured RPO/RTO.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import ssl
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

MAX_REPORT_BYTES = 1024 * 1024


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def utc_timestamp(value):
    if isinstance(value, str):
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            raise ValueError('Backup timestamps must include a timezone')
    elif type(value) is int and value > 0:
        stamp = datetime.fromtimestamp(value, timezone.utc)
    else:
        raise ValueError('Invalid backup timestamp')
    return stamp.astimezone(timezone.utc)


def summarize(document):
    if not isinstance(document, dict):
        raise ValueError('Invalid backup metadata')
    if any(type(document.get(key)) is not bool for key in ('pitr_enabled', 'walg_enabled')):
        raise ValueError('Backup configuration is incomplete')
    backups = document.get('backups')
    if not isinstance(backups, list):
        raise ValueError('Backup inventory is missing')
    completed = []
    for backup in backups:
        if not isinstance(backup, dict) or not isinstance(backup.get('status'), str):
            raise ValueError('Invalid backup inventory entry')
        if backup['status'] == 'COMPLETED':
            completed.append(utc_timestamp(backup['inserted_at']))
    physical = document.get('physical_backup_data')
    earliest = latest = None
    if physical is not None:
        if not isinstance(physical, dict):
            raise ValueError('Invalid physical backup metadata')
        start = physical.get('earliest_physical_backup_date_unix')
        end = physical.get('latest_physical_backup_date_unix')
        if start is not None or end is not None:
            if type(start) is not int or type(end) is not int:
                raise ValueError('Physical backup bounds are incomplete')
            earliest, latest = utc_timestamp(start), utc_timestamp(end)
            if earliest > latest:
                raise ValueError('Physical backup bounds are reversed')
    return {
        'metadata_status': 'observed',
        'pitr_enabled': document['pitr_enabled'],
        'walg_enabled': document['walg_enabled'],
        'backup_entries': len(backups),
        'completed_backup_entries': len(completed),
        'latest_completed_backup_utc': max(completed).isoformat() if completed else None,
        'physical_backup_earliest_utc': earliest.isoformat() if earliest else None,
        'physical_backup_latest_utc': latest.isoformat() if latest else None,
        'backup_availability_observed': bool(completed or latest),
        'restore_drill': 'not_performed',
        'measured_rpo_seconds': None,
        'measured_rto_seconds': None,
        'recovery_verified': False,
    }


def fetch_metadata(project_ref, token):
    if not re.fullmatch(r'[a-z0-9]{20}', project_ref or ''):
        raise ValueError('A valid Supabase project reference is required')
    if not token or '\n' in token or '\r' in token:
        raise ValueError('Configure SUPABASE_ACCESS_TOKEN privately with backups_read permission')
    request = Request(f'https://api.supabase.com/v1/projects/{project_ref}/database/backups',
                      headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/json'},
                      method='GET')
    opener = build_opener(NoRedirects(), HTTPSHandler(context=ssl.create_default_context()))
    with opener.open(request, timeout=30) as response:
        payload = response.read(MAX_REPORT_BYTES + 1)
    if len(payload) > MAX_REPORT_BYTES:
        raise ValueError('Backup metadata exceeds the read limit')
    return json.loads(payload)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-ref', default=os.environ.get('SUPABASE_PROJECT_REF'))
    parser.add_argument('--from-json', type=Path, help='Inspect a private Management API export.')
    args = parser.parse_args(argv)
    source = 'operator_export' if args.from_json else 'supabase_management_api'
    observed = datetime.now(timezone.utc).isoformat()
    try:
        if args.from_json:
            with args.from_json.open('rb') as stream:
                payload = stream.read(MAX_REPORT_BYTES + 1)
            if len(payload) > MAX_REPORT_BYTES:
                raise ValueError('Backup metadata exceeds the read limit')
            document = json.loads(payload)
        else:
            document = fetch_metadata(args.project_ref, os.environ.get('SUPABASE_ACCESS_TOKEN'))
        report = summarize(document)
    except HTTPError as error:
        report = {'metadata_status': 'blocked', 'reason': 'management_api_http_error',
                  'http_status': error.code, 'recovery_verified': False}
    except (ValueError, OSError, URLError, KeyError, TypeError, OverflowError):
        # Never echo credentials, provider response bodies, private paths or raw values.
        report = {'metadata_status': 'blocked',
                  'reason': 'missing_access_or_invalid_metadata', 'recovery_verified': False}
    report.update(source=source, inspected_at_utc=observed)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get('backup_availability_observed') else 2


if __name__ == '__main__':
    raise SystemExit(main())
