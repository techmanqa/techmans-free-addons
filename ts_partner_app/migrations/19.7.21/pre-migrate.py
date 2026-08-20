# "Odoo Enterprise Cost" is being removed (License Cost now covers it, as a
# per-license price x Licenses). Runs BEFORE the column is dropped by _auto_init,
# so any existing value is folded into Maintenance Cost rather than silently lost.
# (Not folded into the new License Cost field: that one is now a per-unit price
# multiplied by Licenses, and most existing assets have Licenses = 0, which would
# zero the migrated amount right back out.)

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    cr.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'partner_asset' AND column_name = 'odoo_enterprise_cost'
    """)
    if not cr.fetchall():
        return

    cr.execute("""
        UPDATE partner_asset
        SET maintenance_cost = COALESCE(maintenance_cost, 0) + odoo_enterprise_cost
        WHERE odoo_enterprise_cost IS NOT NULL AND odoo_enterprise_cost != 0
    """)
    _logger.info("ts_partner_app: migrated %s asset(s)' Odoo Enterprise Cost into Maintenance Cost "
                "before dropping the column.", cr.rowcount)
