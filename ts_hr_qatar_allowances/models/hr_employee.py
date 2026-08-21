from odoo import models, fields, api


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    allowance_ids = fields.One2many(
        'hr.employee.allowance',
        'employee_id',
        string="Allowances",
    )

    allowance_total = fields.Monetary(
        string="Total Allowances",
        compute="_compute_allowance_total",
        store=True,
        currency_field='company_currency_id'
    )

    company_currency_id = fields.Many2one(
        'res.currency',
        related='company_id.currency_id',
        readonly=True,
    )

    gross_salary = fields.Monetary(
        string="Gross Salary",
        compute="_compute_gross_salary",
        store=True,
        currency_field='company_currency_id'
    )

    @api.depends('wage', 'allowance_total')
    def _compute_gross_salary(self):
        for rec in self:
            rec.gross_salary = (rec.wage or 0.0) + (rec.allowance_total or 0.0)

    @api.depends('allowance_ids.amount')
    def _compute_allowance_total(self):
        for rec in self:
            rec.allowance_total = sum(rec.allowance_ids.mapped('amount'))