from odoo import models, fields
from datetime import timedelta


class ResPartner(models.Model):
    _inherit = 'res.partner'

    asset_count = fields.Integer(compute='_compute_asset_counts', string='Odoo Assets Count')
    expiring_soon_count = fields.Integer(compute='_compute_asset_counts', string='Expiring Soon Count')
    infrastructure_id = fields.One2many('partner.infrastructure', 'partner_id',
                                        string='Infrastructure Profile')

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
