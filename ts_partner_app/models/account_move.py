from odoo import api, fields, models

_TRADE_TYPES = ('out_invoice', 'out_refund', 'in_invoice', 'in_refund')
_REVENUE_TYPES = ('out_invoice', 'out_refund')


class AccountMove(models.Model):
    _inherit = 'account.move'

    asset_id = fields.Many2one(
        'partner.asset', string='Client Asset', index=True, copy=False,
        help="Client asset this invoice or vendor bill belongs to. Set it on "
             "recurring supplier bills (hosting, licenses, backups) and on the "
             "client's invoices so the asset can compare real revenue and cost "
             "against the estimate on its Actuals tab.")

    def _ts_partner_app_actual_domain(self):
        """Posted trade documents that count towards an asset's actuals."""
        return [
            ('asset_id', '!=', False),
            ('state', '=', 'posted'),
            ('move_type', 'in', _TRADE_TYPES),
        ]

    @api.model
    def _ts_actuals_domain(self, extra_domain, date_from, date_to, company):
        """Posted customer invoices / vendor bills for an actuals rollup."""
        domain = [
            ('company_id', '=', company.id),
            ('state', '=', 'posted'),
            ('move_type', 'in', _TRADE_TYPES),
        ]
        if date_from:
            domain.append(('invoice_date', '>=', date_from))
        if date_to:
            domain.append(('invoice_date', '<=', date_to))
        return domain + list(extra_domain or [])

    @api.model
    def _ts_actuals_totals(self, extra_domain, date_from, date_to, company, currency):
        """Sum posted revenue (customer invoices - credit notes) and cost
        (vendor bills - refunds) for the given filter, both untaxed and with
        tax, converted to ``currency``. Runs sudo so a Client-Asset manager
        without full accounting access still sees the figures (company pinned).
        """
        company = company or self.env.company
        res = {'revenue_untaxed': 0.0, 'revenue_total': 0.0,
               'cost_untaxed': 0.0, 'cost_total': 0.0, 'count': 0}
        domain = self._ts_actuals_domain(extra_domain, date_from, date_to, company)
        conv_date = date_to or fields.Date.context_today(self)
        groups = self.sudo()._read_group(
            domain,
            groupby=['move_type', 'currency_id'],
            aggregates=['amount_untaxed:sum', 'amount_total:sum', '__count'])
        for move_type, move_currency, untaxed_sum, total_sum, grp_count in groups:
            res['count'] += grp_count
            untaxed = untaxed_sum or 0.0
            total = total_sum or 0.0
            if move_currency and currency and move_currency != currency:
                untaxed = move_currency._convert(untaxed, currency, company, conv_date)
                total = move_currency._convert(total, currency, company, conv_date)
            sign = -1.0 if move_type in ('out_refund', 'in_refund') else 1.0
            if move_type in _REVENUE_TYPES:
                res['revenue_untaxed'] += sign * untaxed
                res['revenue_total'] += sign * total
            else:
                res['cost_untaxed'] += sign * untaxed
                res['cost_total'] += sign * total
        return res
