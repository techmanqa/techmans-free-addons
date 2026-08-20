# "Odoo Client Hub" -> "Client Stack" rebrand. Two records carrying the old name
# live in noupdate="1" data files (data/product_data.xml, data/mail_template_data.xml),
# so a plain module upgrade won't refresh them on already-installed databases. Patch
# them directly so existing installs pick up the new name too.

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})

    product = env.ref('ts_partner_app.product_asset_renewal', raise_if_not_found=False)
    if product and product.description_sale == 'Renewal of a client asset managed via Odoo Client Hub.':
        product.description_sale = 'Renewal of a client asset managed via Client Stack.'

    template = env.ref('ts_partner_app.mail_template_asset_expiry', raise_if_not_found=False)
    if template and template.name == 'Client Hub: Asset Expiry Reminder':
        template.name = 'Client Stack: Asset Expiry Reminder'

    _logger.info("ts_partner_app: rebranded noupdate records from 'Odoo Client Hub' to 'Client Stack'.")
