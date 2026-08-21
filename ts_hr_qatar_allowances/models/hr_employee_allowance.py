from odoo import models, fields


class HrEmployeeAllowance(models.Model):
    _name = 'hr.employee.allowance'
    _description = 'Employee Allowance'

    employee_id = fields.Many2one(
        'hr.employee',
        string="Employee",
        ondelete="cascade",
        required=True,
    )

    allowance_id = fields.Many2one(
        'hr.allowance',
        string="Allowance",
        required=True,
    )

    code = fields.Char(
        related="allowance_id.code",
        store=True,
        readonly=True,
    )

    allowance_type_id = fields.Many2one(
        related="allowance_id.allowance_type_id",
        store=True,
        readonly=True,
    )

    default_amount = fields.Float(
        related="allowance_id.amount",
        readonly=True,
    )

    currency_id = fields.Many2one(
        'res.currency',
        related="employee_id.company_id.currency_id",
        readonly=True,
    )

    amount = fields.Monetary(
        string="Amount",
        currency_field="currency_id",
        required=True,
    )