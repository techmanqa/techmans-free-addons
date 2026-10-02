from odoo import models, fields


class PartnerHostingProvider(models.Model):
    _name = 'partner.hosting.provider'
    _description = 'Hosting Provider'
    _order = 'name'

    _name_uniq = models.Constraint(
        'unique (name)',
        'A hosting provider with this name already exists.',
    )

    name = fields.Char(string='Name', required=True)
    active = fields.Boolean(default=True)
    url = fields.Char(string='Website')
    notes = fields.Text(string='Notes')
