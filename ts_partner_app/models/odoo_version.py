from odoo import models, fields


class OdooVersion(models.Model):
    _name = 'odoo.version'
    _description = 'Odoo Version'
    _order = 'sequence desc, name desc'

    name = fields.Char(string='Version', required=True, translate=False,
                       help="Series number, e.g. 19.0")
    sequence = fields.Integer(
        string='Sequence', default=10,
        help="Higher means newer. Controls ordering and which version counts as "
             "the latest one available.")
    active = fields.Boolean(default=True)
    end_of_support = fields.Date(
        string='End of Support',
        help="Optional. Date Odoo stops supporting this series — for planning "
             "client upgrades.")
    note = fields.Char(string='Note')

    _name_uniq = models.Constraint(
        'unique (name)',
        'This Odoo version is already in the list.',
    )
