"""Explicit local snapshot/drill CLI. No hosted connections, workers or notifications."""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
from cryptography.fernet import Fernet

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from avenra.services.backup_service import IsolatedBackupService


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    generate=commands.add_parser('generate-key')
    generate.add_argument('--key-file',required=True)
    create=commands.add_parser('create')
    create.add_argument('--source-sqlite',required=True)
    create.add_argument('--uploads',required=True)
    restore=commands.add_parser('restore')
    restore.add_argument('--target',required=True)
    restore.add_argument('--isolated',action='store_true')
    for command in (create,restore):
        command.add_argument('--archive',required=True)
        command.add_argument('--key-file',required=True)
    args=parser.parse_args()
    try:
        key_path=Path(args.key_file).expanduser().resolve()
        if args.command=='generate-key':
            key_path.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
            IsolatedBackupService._write(key_path,Fernet.generate_key()+b'\n')
            print('Backup key generated without overwrite. Keep it outside backup storage and logs.')
            return
        archive=Path(args.archive).expanduser().resolve()
        if key_path.is_relative_to(archive.parent):
            parser.error('Keep the encryption key in a separate private directory, outside backup storage.')
        if os.name=='posix' and key_path.stat().st_mode & 0o077:
            parser.error('The key file must have private owner-only permissions.')
        key=key_path.read_bytes().strip()
        service=IsolatedBackupService()
        if args.command=='create':
            result=service.create(args.source_sqlite,args.uploads,archive,key)
        else:
            if not args.isolated: parser.error('Restore requires --isolated and a new target directory.')
            result=service.restore(archive,args.target,key)
            # The path is operator input; report only non-sensitive verification metadata.
            result.pop('database',None)
        print(json.dumps(result,sort_keys=True))
    except (ValueError,OSError,sqlite3.Error):
        parser.exit(2,'Backup/restore failed. No completion confirmed; existing targets are never overwritten.\n')


if __name__=='__main__': main()
