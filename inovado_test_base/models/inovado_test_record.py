from odoo import fields, models


class InovadoTestRecord(models.Model):
    _inherit = "inovado.test.record"

    base_note = fields.Char(string="Base Note")
