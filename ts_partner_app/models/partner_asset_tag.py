from odoo import models, fields


class PartnerAssetTag(models.Model):
    _name = 'partner.asset.tag'
    _description = 'Partner Asset Tag'
    _order = 'name'

    name = fields.Char(string='Tag Name', required=True, translate=True)
    color = fields.Integer(string='Color')

    _name_uniq = models.Constraint(
        'unique (name)',
        'Tag name already exists!',
    )
