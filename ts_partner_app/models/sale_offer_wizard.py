from odoo import models, fields, api, _
from odoo.exceptions import UserError


class PartnerSaleOfferWizard(models.TransientModel):
    _name = 'partner.sale.offer.wizard'
    _description = 'Create Sale Offer from Service Products'

    asset_id = fields.Many2one('partner.asset', required=True)
    partner_id = fields.Many2one(related='asset_id.partner_id', string='Client', readonly=True)
    currency_id = fields.Many2one(related='asset_id.currency_id', readonly=True)
    line_ids = fields.One2many('partner.sale.offer.wizard.line', 'wizard_id', string='Services')
    selected_count = fields.Integer(compute='_compute_totals')
    total_amount = fields.Monetary(compute='_compute_totals', currency_field='currency_id')

    @api.depends('line_ids.selected', 'line_ids.quantity', 'line_ids.price_unit')
    def _compute_totals(self):
        for wizard in self:
            selected = wizard.line_ids.filtered('selected')
            wizard.selected_count = len(selected)
            wizard.total_amount = sum(line.quantity * line.price_unit for line in selected)

    @api.model_create_multi
    def create(self, vals_list):
        wizards = super().create(vals_list)
        wizards._populate_lines()
        return wizards

    def _populate_lines(self):
        """Only template tasks that already have a linked product (Configuration >
        Import Products) can become a quotation line — done as an explicit write right
        after create(), same pattern as the New Client Project wizard, so the wizard is
        a fully-persisted record with real child rows before the dialog ever opens."""
        templates = self.env['partner.project.template.task'].search([('product_id', '!=', False)])
        Line = self.env['partner.sale.offer.wizard.line']
        for wizard in self:
            Line.create([{
                'wizard_id': wizard.id,
                'template_task_id': tmpl.id,
                'product_id': tmpl.product_id.id,
                'name': tmpl.name,
                'phase': tmpl.phase,
                'sequence': tmpl.sequence,
                'default_hours': tmpl.default_hours,
                'quantity': 1,
                'price_unit': tmpl.product_id.list_price,
                'selected': False,
            } for tmpl in templates])

    def action_create_quotation(self):
        self.ensure_one()
        selected = self.line_ids.filtered('selected')
        if not selected:
            raise UserError(_("Select at least one service before creating the quotation."))
        order = self.env['sale.order'].create({
            'partner_id': self.partner_id.id,
            'origin': self.asset_id.name,
            'asset_id': self.asset_id.id,
        })
        self.env['sale.order.line'].create([{
            'order_id': order.id,
            'product_id': line.product_id.id,
            'name': line.name,
            'product_uom_qty': line.quantity,
            'price_unit': line.price_unit,
        } for line in selected.sorted('sequence')])
        self.asset_id.message_post(body=_(
            "Sale offer %(order)s created with %(count)s service(s).",
            order=order.name, count=len(selected)))
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order',
            'res_id': order.id,
            'view_mode': 'form',
            'target': 'current',
        }


class PartnerSaleOfferWizardLine(models.TransientModel):
    _name = 'partner.sale.offer.wizard.line'
    _description = 'Create Sale Offer Wizard Line'
    _order = 'sequence, id'

    wizard_id = fields.Many2one('partner.sale.offer.wizard', required=True, ondelete='cascade')
    template_task_id = fields.Many2one('partner.project.template.task')
    product_id = fields.Many2one('product.product', required=True)
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
    ], required=True)
    name = fields.Char(required=True)
    default_hours = fields.Float(readonly=True)
    quantity = fields.Float(string='Quantity', default=1)
    price_unit = fields.Float(string='Unit Price')
    selected = fields.Boolean(default=False)
