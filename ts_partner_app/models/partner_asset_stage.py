from odoo import models, fields

class PartnerAssetStage(models.Model):
    _name = 'partner.asset.stage'
    _description = 'Partner Asset Stage'
    _order = 'sequence, id'

    name = fields.Char(string='Stage Name', required=True, translate=True)
    sequence = fields.Integer(string='Sequence', default=1)
    fold = fields.Boolean(string='Folded in Kanban', default=False)
    description = fields.Text(string='Description')
    color = fields.Integer(string='Kanban Color', default=0,
                           help="Cards in this stage take this color on the Kanban board.")
