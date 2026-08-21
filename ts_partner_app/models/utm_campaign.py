from odoo import models, fields, _


class UtmCampaign(models.Model):
    _inherit = 'utm.campaign'

    asset_count = fields.Integer(compute='_compute_asset_count', string='Client Assets Count')

    def _compute_asset_count(self):
        counts = {
            campaign.id: count
            for campaign, count in self.env['partner.asset']._read_group(
                [('campaign_id', 'in', self.ids)], groupby=['campaign_id'], aggregates=['__count'])
        }
        for campaign in self:
            campaign.asset_count = counts.get(campaign.id, 0)

    def action_view_assets(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id("ts_partner_app.partner_asset_action")
        action['domain'] = [('campaign_id', '=', self.id)]
        action['context'] = {'default_campaign_id': self.id}
        return action
