from odoo import models, fields, _
from dateutil.relativedelta import relativedelta


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    asset_id = fields.Many2one('partner.asset', string='Client Asset',
                               help="Set automatically when this order was created from a client asset "
                                    "(renewal quote or one-off invoice), so it shows up on that asset's "
                                    "Invoices smart button.")

    def action_confirm(self):
        res = super().action_confirm()
        assets = self.env['partner.asset'].search([
            ('sale_order_id', 'in', self.ids),
            ('state', '=', 'to_renew'),
        ])
        if assets:
            running_stage = self.env.ref('ts_partner_app.stage_running', raise_if_not_found=False)
            for asset in assets:
                base_date = asset.end_date or fields.Date.context_today(asset)
                new_end = base_date + relativedelta(months=asset.renewal_period or 12)
                vals = {
                    'start_date': asset.end_date or asset.start_date,
                    'end_date': new_end,
                    'state': 'running',
                    'expiry_notified': False,
                }
                if running_stage:
                    vals['stage_id'] = running_stage.id
                asset.write(vals)
                asset.message_post(body=_(
                    "Renewal confirmed via %(order)s. End date extended to %(date)s.",
                    order=asset.sale_order_id.name, date=new_end))
        return res
