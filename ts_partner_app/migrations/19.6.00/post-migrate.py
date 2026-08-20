# Encrypt legacy plaintext credentials.
#
# In earlier versions, `password` and `password2` were stored Char columns
# containing plaintext. In 19.6.00 they became non-stored computed fields
# backed by `password_encrypted` / `password2_encrypted`. Odoo does not drop
# the old columns on upgrade, so this script moves the plaintext values into
# the encrypted columns and then wipes the plaintext.

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    Asset = env['partner.asset']

    cr.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'partner_asset'
          AND column_name IN ('password', 'password2')
    """)
    legacy_cols = [row[0] for row in cr.fetchall()]
    if not legacy_cols:
        return

    fernet = Asset._get_fernet()
    if fernet is None:
        _logger.warning("cryptography not available; skipping credential encryption migration.")
        return

    cr.execute("SELECT id, %s FROM partner_asset" % ", ".join(legacy_cols))
    migrated = 0
    for row in cr.fetchall():
        rec_id = row[0]
        sets, params = [], []
        for idx, col in enumerate(legacy_cols, start=1):
            value = row[idx]
            if value:
                sets.append("%s_encrypted = %%s" % col)
                params.append(fernet.encrypt(value.encode()).decode())
        if sets:
            params.append(rec_id)
            cr.execute("UPDATE partner_asset SET %s WHERE id = %%s" % ", ".join(sets), params)
            migrated += 1

    # Wipe the plaintext copies.
    cr.execute("UPDATE partner_asset SET %s" % ", ".join("%s = NULL" % c for c in legacy_cols))
    _logger.info("ts_partner_app: encrypted credentials for %s asset(s) and wiped plaintext columns.", migrated)
