from odoo import models, fields


class PartnerProjectTemplateTask(models.Model):
    _name = 'partner.project.template.task'
    _description = 'Client Project Template Task'
    _order = 'sequence, id'

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    phase = fields.Selection([
        ('discovery', 'Discovery & Planning'),
        ('foundation', 'Environment & Foundation'),
        ('modules', 'Module Configuration'),
        ('migration', 'Data Migration'),
        ('integration', 'Integrations & Customization'),
        ('testing', 'Testing'),
        ('training', 'Training & Go-Live'),
        ('pm', 'Project Management'),
    ], required=True, default='discovery')
    default_hours = fields.Float(
        string='Default Hours',
        help="Suggested planned hours, used to pre-fill the New Client Project wizard. "
             "Editable per selection there.")
    note = fields.Char(translate=True, help="Shown next to the task in the wizard, e.g. an hour range or condition.")
    active = fields.Boolean(default=True)
    product_id = fields.Many2one('product.product', string='Linked Product', readonly=True, copy=False,
                                  help="Set by Configuration > Import Products — the Sales service product "
                                       "generated from this template task, priced at Default Hours × the "
                                       "hourly rate used at import time.")
