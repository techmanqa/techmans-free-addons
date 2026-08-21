from odoo import models, fields

class PartnerAssetCustomModule(models.Model):
    _name = 'partner.asset.custom.module'
    _description = 'Partner Asset Custom Module'
    _order = 'name'

    name = fields.Char(string='Module Name', required=True)
    version = fields.Char(string='Version')
    author = fields.Char(string='Author')
    link = fields.Char(string='Link')
    asset_id = fields.Many2one('partner.asset', string='Asset', ondelete='cascade')
