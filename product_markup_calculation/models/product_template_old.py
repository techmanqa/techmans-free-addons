from odoo import models, fields, api

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    custom_field_1 = fields.Selection(
        [(str(i), str(i)) for i in range(0, 100, 5)],
        string="Mark Up in %"
    )
    custom_field_2 = fields.Float(string="Total Mark Up", compute="_compute_custom_field_2", store=True)

    @api.depends('standard_price', 'custom_field_1')
    def _compute_custom_field_2(self):
        for record in self:
            try:
                percentage = float(record.custom_field_1) / 100 if record.custom_field_1 else 0
                record.custom_field_2 = record.standard_price + (record.standard_price * percentage)
            except ValueError:
                record.custom_field_2 = 0.0
