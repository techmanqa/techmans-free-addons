# Remap partner.asset.type from the old 8-value list to the new 3-value one:
# domain / hosting / email / ssl / other -> online, git / server -> custom,
# odoo_sh is unchanged.

import logging

_logger = logging.getLogger(__name__)

_REMAP = {
    'domain': 'online',
    'hosting': 'online',
    'email': 'online',
    'ssl': 'online',
    'other': 'online',
    'git': 'custom',
    'server': 'custom',
}


def migrate(cr, version):
    cr.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'partner_asset' AND column_name = 'type'
    """)
    if not cr.fetchall():
        return

    total = 0
    for old_value, new_value in _REMAP.items():
        cr.execute(
            "UPDATE partner_asset SET type = %s WHERE type = %s",
            (new_value, old_value),
        )
        total += cr.rowcount
    _logger.info("ts_partner_app: remapped type on %s asset(s) to the new online/odoo_sh/custom list.", total)
