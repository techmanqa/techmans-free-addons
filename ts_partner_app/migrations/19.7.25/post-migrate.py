# Vendor field fully removed (field + data, per explicit request — no replacement,
# nothing to preserve). The expiry reminder email template lives in a noupdate="1"
# data file, so its body won't refresh with the new copy on its own, and its old body
# still references the now-gone vendor_id field, which mail.template's own render-safety
# check refuses to save. Overwrite it outright with the current template body instead of
# trying to patch it (the stored HTML's exact whitespace isn't guaranteed to match).

import logging

_logger = logging.getLogger(__name__)

_NEW_BODY = """<div style="margin:0px;padding:0px;font-size:14px;">
    <p>Hello <t t-out="object.user_id.name or ''"/>,</p>
    <p>
        The asset <strong t-out="object.name"/>
        (<t t-out="dict(object._fields['type']._description_selection(object.env)).get(object.type, object.type)"/>)
        for customer <strong t-out="object.partner_id.name or ''"/> is approaching its end date.
    </p>
    <ul>
        <li>End date: <t t-out="object.end_date or ''"/></li>
        <li>Monthly billing: <t t-out="object.monthly_billing_client or 0"/> <t t-out="object.currency_id.name or ''"/></li>
    </ul>
    <p>Please handle the renewal in time.</p>
</div>
"""


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    template = env.ref('ts_partner_app.mail_template_asset_expiry', raise_if_not_found=False)
    if template and template.body_html and 'vendor_id' in template.body_html:
        template.body_html = _NEW_BODY
        _logger.info("ts_partner_app: rewrote the expiry reminder email template to drop the "
                    "now-removed Vendor line.")
