from odoo import _, fields, models
from odoo.exceptions import UserError


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # Surface Odoo's built-in currency-rate provider here so the numbers on the
    # Cost & Margin tab (License Currency -> local currency) have real rates to
    # convert with, without hunting through the Accounting settings.
    ts_currency_provider = fields.Selection(
        related='company_id.currency_provider', readonly=False,
        string='Currency Rate Provider')
    ts_currency_interval_unit = fields.Selection(
        related='company_id.currency_interval_unit', readonly=False,
        string='Currency Rate Sync Interval')
    ts_currency_next_execution_date = fields.Date(
        related='company_id.currency_next_execution_date', readonly=False,
        string='Next Currency Rate Sync')

    def action_ts_update_currency_rates(self):
        """Fetch exchange rates now from the configured provider (same job the
        'Automatic Currency Rates' cron runs)."""
        self.ensure_one()
        if not self.company_id.currency_provider:
            raise UserError(_("Pick a Currency Rate Provider first."))
        cron = self.env.ref('base.ir_cron_currency_rate_live', raise_if_not_found=False)
        if cron:
            cron.sudo().method_direct_trigger()
        elif hasattr(self.env['res.company'], 'update_currency_rates'):
            self.env['res.company'].sudo().search(
                [('currency_provider', '!=', False)]).update_currency_rates()
        else:
            raise UserError(_("Automatic currency rates are not available on this database."))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': 'success',
                'message': _("Currency rates updated from %s.", self.company_id.currency_provider),
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }
