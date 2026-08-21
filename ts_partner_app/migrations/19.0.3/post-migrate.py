# Infra Monthly Cost / Gross Margin used to sum every cost line unconditionally. Each
# cost line now has a "Billed by Us" toggle (maintenance defaults on, everything else
# defaults off, matching how these clients are actually billed) and only toggled-on
# lines count towards the margin. Changing what a stored compute field depends on does
# NOT retroactively recompute it for existing rows on upgrade — only genuinely new
# stored fields get that treatment — so existing assets are left with stale
# infra_monthly_cost/gross_margin values (still summing everything) until forced here.

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})

    assets = env['partner.asset'].search([])
    if not assets:
        return
    assets._compute_infra_monthly_cost()
    assets._compute_gross_margin()
    env.flush_all()
    _logger.info("ts_partner_app: recomputed Infra Monthly Cost / Gross Margin for %s asset(s) "
                "now that only 'Billed by Us' cost lines count.", len(assets))
