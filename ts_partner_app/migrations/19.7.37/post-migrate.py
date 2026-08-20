# The "Odoo Client Hub" -> "Client Stack" rebrand (19.7.08) patched the noupdate
# records that carried the old name, but missed ir.module.module.shortdesc itself —
# that field is only refreshed from the manifest on "Update Apps List", not on a
# plain module upgrade, so already-installed databases kept showing the old name
# in Apps. Patch it directly.

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})

    module = env['ir.module.module'].search([('name', '=', 'ts_partner_app')], limit=1)
    if module and module.shortdesc == 'Odoo Client Hub':
        module.shortdesc = 'Client Stack'
        _logger.info("ts_partner_app: fixed ir.module.module.shortdesc to 'Client Stack'.")
