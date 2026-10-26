"""Explicit operator CLI only; no browser-accessible destructive maintenance."""
import json
import os
import sqlite3
import click
from flask import current_app
import db
from avenra.controllers.diary_controller import get_uploads_dir
from avenra.repositories.user_repository import UserRepository
from avenra.services.retention_service import RetentionService


def register_retention(app):
    def service_and_actor(actor_id):
        conn=db.get_db()
        actor=UserRepository(conn).get_by_id(actor_id)
        if actor is None: raise click.ClickException('Active assigned admin required.')
        return RetentionService(conn,get_uploads_dir()),actor

    def authorize_target(allowed):
        if not allowed and (current_app.config['APP_ENV']=='production' or os.environ.get('DATABASE_URL') or os.environ.get('VERCEL')):
            raise click.ClickException('Hosted/production changes require explicit --allow-hosted-apply and prior approval.')

    def execute(operation):
        try: click.echo(json.dumps(operation(),sort_keys=True))
        except (ValueError,PermissionError) as error:
            raise click.ClickException(str(error)) from None
        except (sqlite3.Error,OSError,RuntimeError):
            raise click.ClickException('Maintenance unavailable; no completion confirmed. Inspect the non-sensitive job state before retrying.') from None

    @app.cli.command('retention')
    @click.option('--actor-id',required=True,type=click.IntRange(min=1,max=2**63-1))
    @click.option('--case-code',required=True)
    @click.option('--kind',required=True,type=click.Choice(['diary','alert-location']))
    @click.option('--before')
    @click.option('--entry-id',multiple=True,type=click.IntRange(min=1,max=2**63-1))
    @click.option('--apply',is_flag=True,help='Default is read-only preview.')
    @click.option('--confirm-plan')
    @click.option('--verification-reference')
    @click.option('--allow-hosted-apply',is_flag=True)
    def retention(actor_id,case_code,kind,before,entry_id,apply,confirm_plan,verification_reference,allow_hosted_apply):
        """Preview up to 100 exact records; apply only the approved unchanged plan."""
        service,actor=service_and_actor(actor_id)
        scope={'before':before,'entry_ids':list(entry_id) if entry_id else None}
        if apply:
            if not confirm_plan or not verification_reference:
                raise click.ClickException('Confirm the exact preview plan and approval reference before applying.')
            authorize_target(allow_hosted_apply)
            execute(lambda:service.apply(actor,case_code,kind,confirm_plan,verification_reference,**scope))
        else:
            execute(lambda:service.preview(actor,case_code,kind,**scope))

    @app.cli.command('retention-hold')
    @click.option('--actor-id',required=True,type=click.IntRange(min=1,max=2**63-1))
    @click.option('--case-code',required=True)
    @click.option('--state',required=True,type=click.Choice(['hold','release']))
    @click.option('--verification-reference',required=True)
    @click.option('--allow-hosted-apply',is_flag=True)
    def hold(actor_id,case_code,state,verification_reference,allow_hosted_apply):
        """Record or release an approved hold without altering existing evidence."""
        authorize_target(allow_hosted_apply)
        service,actor=service_and_actor(actor_id)
        def operation():
            service.set_hold(actor,case_code,state=='hold',verification_reference)
            return {'hold':state=='hold'}
        execute(operation)

    @app.cli.command('retention-media')
    @click.option('--actor-id',required=True,type=click.IntRange(min=1,max=2**63-1))
    @click.option('--case-code',required=True)
    @click.option('--apply',is_flag=True)
    @click.option('--verification-reference')
    @click.option('--allow-hosted-apply',is_flag=True)
    def media(actor_id,case_code,apply,verification_reference,allow_hosted_apply):
        """Preview or process at most ten previously approved media cleanup jobs."""
        if apply: authorize_target(allow_hosted_apply)
        service,actor=service_and_actor(actor_id)
        execute(lambda:service.cleanup_media(actor,case_code,apply=apply,reference=verification_reference))
