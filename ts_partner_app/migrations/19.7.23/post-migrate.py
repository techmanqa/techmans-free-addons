# Reminder window default changed from 30 to 60 days. Bump any asset still
# sitting at the old default (30) up to the new one — but leave assets where
# someone deliberately chose a different value (e.g. a 14-day SSL reminder)
# alone, since that's an intentional override, not the default.
#
# Done through the ORM (not raw SQL) so the dependent Expiry Date recomputes
# correctly for every asset touched.

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    assets = env['partner.asset'].search([('reminder_days', '=', 30)])
    if assets:
        assets.write({'reminder_days': 60})
    _logger.info("ts_partner_app: bumped the reminder window from 30 to 60 days on %s asset(s) "
                "still at the old default.", len(assets))
