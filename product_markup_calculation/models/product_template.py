from odoo import models, fields, api

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    markup_percent = fields.Float(
        string="Markup %",
        digits=(5, 2),
        help="Enter the markup percentage to apply on cost"
    )

    total_markup = fields.Float(
        string="Total MarkUp",
        compute="_compute_total_markup",
        store=True,
        readonly=True
    )

    @api.depends('standard_price', 'markup_percent')
    def _compute_total_markup(self):
        for record in self:
            if record.standard_price and record.markup_percent:
                record.total_markup = record.standard_price * (1 + (record.markup_percent / 100.0))
            else:
                record.total_markup = record.standard_price or 0.0
