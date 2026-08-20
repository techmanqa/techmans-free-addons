from odoo import models, fields, api

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    markup_percent = fields.Float(
        string="Markup %",
        digits=(5, 2),
        company_dependent=True,
        groups="base.group_user",
        help="Enter the markup percentage to apply on cost. This value can differ per company."
    )

    total_markup = fields.Float(
        string="Total MarkUp",
        compute="_compute_total_markup",
        store=True,
        company_dependent=True,
        readonly=True,
        groups="base.group_user",
    )

    @api.depends('standard_price', 'markup_percent')
    def _compute_total_markup(self):
        for record in self:
            record.total_markup = record.standard_price * (1 + (record.markup_percent / 100.0))
            record.list_price = record.total_markup
