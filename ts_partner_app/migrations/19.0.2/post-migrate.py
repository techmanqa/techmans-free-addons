# The dashboard and "Client Projects" menu used to list every project.project in the
# database (minus the one hardcoded "Client Tasks" exclusion), which swept in unrelated
# projects on multi-project databases. They're now scoped to a "Client App" tag applied
# when a client project is created. Backfill that tag onto client projects created before
# this change (identified by partner_id, same as _get_or_create_client_project's lookup),
# so they don't silently vanish from the dashboard after the upgrade.

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})

    tag = env.ref('ts_partner_app.project_tag_client_app', raise_if_not_found=False)
    shared_project = env.ref('ts_partner_app.project_client_tasks', raise_if_not_found=False)
    if not tag:
        return

    projects = env['project.project'].search([
        ('partner_id', '!=', False),
        ('id', '!=', shared_project.id if shared_project else 0),
        ('tag_ids', 'not in', tag.id),
    ])
    if projects:
        projects.write({'tag_ids': [(4, tag.id)]})
    _logger.info("ts_partner_app: tagged %s pre-existing client project(s) with 'Client App' "
                "so they stay visible on the dashboard.", len(projects))
