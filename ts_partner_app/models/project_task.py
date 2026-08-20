from odoo import models, fields


class ProjectTask(models.Model):
    _inherit = 'project.task'

    asset_id = fields.Many2one('partner.asset', string='Client Asset', index=True,
                               help="Client asset (domain, hosting, server…) this task relates to.")
