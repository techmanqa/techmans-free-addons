from odoo import models, fields, api, _
from odoo.exceptions import UserError


class PartnerAssetTaskLinkWizard(models.TransientModel):
    _name = 'partner.asset.task.link.wizard'
    _description = 'Link Existing Tasks to a Client Asset'

    asset_id = fields.Many2one('partner.asset', string='Client Asset', required=True)
    partner_id = fields.Many2one(related='asset_id.partner_id', string='Client', readonly=True)
    project_id = fields.Many2one(related='asset_id.project_id', string='Project', readonly=True)
    only_unassigned = fields.Boolean(
        string='Hide tasks already linked to another asset', default=True)
    task_ids = fields.Many2many('project.task', string='Tasks')

    @api.onchange('only_unassigned', 'asset_id')
    def _onchange_filter(self):
        """Drop any picked tasks that no longer match the filter so the selection
        stays consistent with the domain shown to the user."""
        if self.only_unassigned:
            self.task_ids = self.task_ids.filtered(
                lambda t: not t.asset_id or t.asset_id == self.asset_id)

    def action_link(self):
        self.ensure_one()
        if not self.task_ids:
            raise UserError(_("Select at least one task to link."))
        self.task_ids.write({'asset_id': self.asset_id.id})
        self.asset_id.message_post(body=_(
            "%(count)s task(s) linked to this asset: %(names)s",
            count=len(self.task_ids),
            names=", ".join(self.task_ids.mapped('display_name'))))
        return {'type': 'ir.actions.act_window_close'}
