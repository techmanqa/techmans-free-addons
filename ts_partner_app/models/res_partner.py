import re

from odoo import api, models, fields, _
from datetime import timedelta
from dateutil.relativedelta import relativedelta

CLIENT_REF_SEQUENCE_CODE = 'ts_partner_app.client_reference'


class ResPartner(models.Model):
    _inherit = 'res.partner'

    client_ref = fields.Char(
        string='Client Reference', readonly=True, copy=False, index=True,
        help="Auto-generated from the client's name and a running number. "
             "Its numbering (next number, padding, ...) is configured in "
             "Settings > Technical > Sequences & Identifiers > Sequences.")
    asset_count = fields.Integer(compute='_compute_asset_counts', string='Odoo Assets Count')
    expiring_soon_count = fields.Integer(compute='_compute_asset_counts', string='Expiring Soon Count')
    infrastructure_id = fields.One2many('partner.infrastructure', 'partner_id',
                                        string='Infrastructure Profile')
    environment_ids = fields.One2many('partner.environment', 'partner_id',
                                      string='Odoo Environments')
    environment_count = fields.Integer(compute='_compute_environment_count',
                                       string='Odoo Environments Count')

    # ------------------------------------------------------------------
    # Client Actuals — a period rollup of everything invoiced to / spent on
    # this client, straight totals (not per month). One-off project work
    # (implementation, migration) is counted as-is.
    # ------------------------------------------------------------------
    client_actuals_period = fields.Selection([
        ('this_year', 'This Year'),
        ('trailing_12m', 'Trailing 12 Months'),
        ('all_time', 'All Time'),
        ('custom', 'Custom'),
    ], string='Client Actuals Period', default='trailing_12m', required=True)
    client_actuals_date_from = fields.Date(
        string='Actuals From', compute='_compute_client_actuals_dates',
        store=True, readonly=False)
    client_actuals_date_to = fields.Date(
        string='Actuals To', compute='_compute_client_actuals_dates',
        store=True, readonly=False)
    client_actuals_currency_id = fields.Many2one(
        'res.currency', string='Actuals Currency', compute='_compute_client_actuals_currency')
    client_actual_revenue = fields.Monetary(
        string='Client Revenue (untaxed)', compute='_compute_client_actuals',
        currency_field='client_actuals_currency_id',
        help="All posted customer invoices minus credit notes for this client "
             "(and its contacts) in the period.")
    client_actual_revenue_total = fields.Monetary(
        string='Client Revenue (with tax)', compute='_compute_client_actuals',
        currency_field='client_actuals_currency_id')
    client_actual_cost = fields.Monetary(
        string='Client Cost (untaxed)', compute='_compute_client_actuals',
        currency_field='client_actuals_currency_id',
        help="Posted vendor bills minus refunds tagged (via Client Asset) to any "
             "of this client's assets, in the period.")
    client_actual_cost_total = fields.Monetary(
        string='Client Cost (with tax)', compute='_compute_client_actuals',
        currency_field='client_actuals_currency_id')
    client_actual_margin = fields.Monetary(
        string='Client Margin (untaxed)', compute='_compute_client_actuals',
        currency_field='client_actuals_currency_id')
    client_actual_margin_total = fields.Monetary(
        string='Client Margin (with tax)', compute='_compute_client_actuals',
        currency_field='client_actuals_currency_id')
    client_actual_move_count = fields.Integer(
        string='Client Documents', compute='_compute_client_actuals')

    def _compute_client_actuals_currency(self):
        currency = self.env.company.currency_id
        for partner in self:
            partner.client_actuals_currency_id = currency

    @api.depends('client_actuals_period')
    def _compute_client_actuals_dates(self):
        today = fields.Date.context_today(self)
        for partner in self:
            period = partner.client_actuals_period
            if period == 'this_year':
                partner.client_actuals_date_from = today.replace(month=1, day=1)
                partner.client_actuals_date_to = today
            elif period == 'trailing_12m':
                partner.client_actuals_date_from = today - relativedelta(months=12)
                partner.client_actuals_date_to = today
            elif period == 'all_time':
                partner.client_actuals_date_from = False
                partner.client_actuals_date_to = False
            else:  # custom -- keep whatever is there
                partner.client_actuals_date_from = partner.client_actuals_date_from
                partner.client_actuals_date_to = partner.client_actuals_date_to

    def _client_actuals_asset_ids(self):
        self.ensure_one()
        commercial = self.commercial_partner_id
        return self.env['partner.asset'].sudo().search([
            ('partner_id', 'child_of', commercial.id),
        ]).ids

    @api.depends('client_actuals_date_from', 'client_actuals_date_to')
    def _compute_client_actuals(self):
        Move = self.env['account.move']
        company = self.env.company
        currency = company.currency_id
        for partner in self:
            if not partner.id:
                partner.client_actual_revenue = partner.client_actual_revenue_total = 0.0
                partner.client_actual_cost = partner.client_actual_cost_total = 0.0
                partner.client_actual_margin = partner.client_actual_margin_total = 0.0
                partner.client_actual_move_count = 0
                continue
            commercial = partner.commercial_partner_id
            df, dt = partner.client_actuals_date_from, partner.client_actuals_date_to
            revenue = Move._ts_actuals_totals(
                [('partner_id', 'child_of', commercial.id),
                 ('move_type', 'in', ('out_invoice', 'out_refund'))],
                df, dt, company, currency)
            asset_ids = partner._client_actuals_asset_ids()
            cost = Move._ts_actuals_totals(
                [('asset_id', 'in', asset_ids or [0]),
                 ('move_type', 'in', ('in_invoice', 'in_refund'))],
                df, dt, company, currency)
            partner.client_actual_revenue = revenue['revenue_untaxed']
            partner.client_actual_revenue_total = revenue['revenue_total']
            partner.client_actual_cost = cost['cost_untaxed']
            partner.client_actual_cost_total = cost['cost_total']
            partner.client_actual_margin = revenue['revenue_untaxed'] - cost['cost_untaxed']
            partner.client_actual_margin_total = revenue['revenue_total'] - cost['cost_total']
            partner.client_actual_move_count = revenue['count'] + cost['count']

    def action_view_client_moves(self):
        self.ensure_one()
        commercial = self.commercial_partner_id
        asset_ids = self._client_actuals_asset_ids()
        domain = [
            ('state', '=', 'posted'),
            ('company_id', '=', self.env.company.id),
            '|',
            '&', ('move_type', 'in', ('out_invoice', 'out_refund')),
                 ('partner_id', 'child_of', commercial.id),
            '&', ('move_type', 'in', ('in_invoice', 'in_refund')),
                 ('asset_id', 'in', asset_ids or [0]),
        ]
        if self.client_actuals_date_from:
            domain.append(('invoice_date', '>=', self.client_actuals_date_from))
        if self.client_actuals_date_to:
            domain.append(('invoice_date', '<=', self.client_actuals_date_to))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Client Invoices & Bills'),
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': domain,
        }

    @api.model_create_multi
    def create(self, vals_list):
        partners = super().create(vals_list)
        for partner in partners:
            # Only top-level partners are "clients" — sub-contacts and
            # addresses (delivery/invoice/employee) created under a company
            # don't get their own reference.
            if not partner.parent_id:
                partner.client_ref = partner._generate_client_ref()
        return partners

    def _generate_client_ref(self):
        self.ensure_one()
        prefix = re.sub(r'[^A-Z0-9]', '', (self.name or '').upper())[:4] or 'CLI'
        number = self.env['ir.sequence'].sudo().next_by_code(CLIENT_REF_SEQUENCE_CODE) or '0'
        return f"{prefix}-{number}"

    def _compute_asset_counts(self):
        today = fields.Date.context_today(self)
        soon = today + timedelta(days=30)
        Asset = self.env['partner.asset']

        # Two grouped queries for the whole batch (no per-partner search).
        total = {
            partner.id: count
            for partner, count in Asset._read_group(
                [('partner_id', 'in', self.ids)],
                groupby=['partner_id'], aggregates=['__count'])
        }
        expiring = {
            partner.id: count
            for partner, count in Asset._read_group(
                [('partner_id', 'in', self.ids),
                 ('expiry_date', '>=', today),
                 ('expiry_date', '<=', soon)],
                groupby=['partner_id'], aggregates=['__count'])
        }
        for partner in self:
            partner.asset_count = total.get(partner.id, 0)
            partner.expiring_soon_count = expiring.get(partner.id, 0)

    def action_view_partner_assets(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id("ts_partner_app.partner_asset_action")
        action['domain'] = [('partner_id', '=', self.id)]
        action['context'] = {'default_partner_id': self.id}
        return action

    def _compute_environment_count(self):
        counts = {
            partner.id: count
            for partner, count in self.env['partner.environment']._read_group(
                [('partner_id', 'in', self.ids)],
                groupby=['partner_id'], aggregates=['__count'])
        }
        for partner in self:
            partner.environment_count = counts.get(partner.id, 0)

    def action_view_infrastructure(self):
        self.ensure_one()
        infra = self.infrastructure_id[:1]
        action = self.env["ir.actions.actions"]._for_xml_id("ts_partner_app.partner_infrastructure_action")
        action['view_mode'] = 'form'
        action['views'] = [(False, 'form')]
        action['res_id'] = infra.id if infra else False
        action['context'] = {'default_partner_id': self.id}
        return action

    def action_view_environments(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id("ts_partner_app.partner_environment_action")
        action['domain'] = [('partner_id', '=', self.id)]
        action['context'] = {'default_partner_id': self.id}
        return action

    def action_view_expiring_soon_assets(self):
        self.ensure_one()
        today = fields.Date.context_today(self)
        soon = today + timedelta(days=30)
        action = self.env["ir.actions.actions"]._for_xml_id("ts_partner_app.partner_asset_action")
        action['domain'] = [('partner_id', '=', self.id),
                            ('expiry_date', '>=', today),
                            ('expiry_date', '<=', soon)]
        action['context'] = {'default_partner_id': self.id}
        return action
