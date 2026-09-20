from odoo import fields, models


class InovadoTestRecord(models.Model):
    _name = "inovado.test.record"
    _description = "Inovado Test Record"

    name = fields.Char(required=True)
