from odoo import models, fields


class PartnerAssetNativeModule(models.Model):
    _name = 'partner.asset.native.module'
    _description = 'Native Odoo App'
    _order = 'name'

    name = fields.Char(string='App Name', required=True, translate=True)

    _name_uniq = models.Constraint(
        'unique (name)',
        'This native app is already in the list.',
    )
