from odoo import models, fields

class HrAllowanceType(models.Model):
    _name = 'hr.allowance.type'
    _description = 'Allowance Type'
    _order = 'type_code'

    name = fields.Char(string='Type Name', required=True)
    description = fields.Text(string='Description')  # 🟢 Added this line
    type_code = fields.Char(string='Type Code', required=True)
    active = fields.Boolean(string='Active', default=True)

    _sql_constraints = [
        ('type_code_unique', 'unique(type_code)', 'Each allowance type must have a unique code.')
    ]