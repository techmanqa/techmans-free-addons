from odoo import fields, models


class InovadoTestRecord(models.Model):
    _inherit = "inovado.test.record"

    addon_note = fields.Char(string="Addon Note")
