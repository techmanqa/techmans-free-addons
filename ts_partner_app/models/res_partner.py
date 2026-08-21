import re

from odoo import api, models, fields
from datetime import timedelta

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

    def action_view_infrastructure(self):
        self.ensure_one()
        infra = self.infrastructure_id[:1]
        action = self.env["ir.actions.actions"]._for_xml_id("ts_partner_app.partner_infrastructure_action")
        action['view_mode'] = 'form'
        action['views'] = [(False, 'form')]
        action['res_id'] = infra.id if infra else False
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
