from odoo import models, fields, _
from odoo.exceptions import UserError


class PartnerProjectTemplateTaskImportWizard(models.TransientModel):
    _name = 'partner.project.template.task.import.wizard'
    _description = 'Import Products from Project Task Templates'

    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)
    hourly_rate = fields.Monetary(
        string='Hourly Rate', currency_field='currency_id',
        help="Each template task's product is priced at its Default Hours multiplied by this rate. "
             "Leave at 0 to import the products with hours recorded in the description but the price "
             "left at 0 for you to set manually per product.")

    def action_import_products(self):
        self.ensure_one()
        templates = self.env['partner.project.template.task'].search([])
        phase_labels = dict(templates._fields['phase']._description_selection(self.env)) if templates \
            else dict(self.env['partner.project.template.task']._fields['phase']._description_selection(self.env))
        product_ids = []
        for tmpl in templates:
            vals = {
                'name': tmpl.name,
                'type': 'service',
                'sale_ok': True,
                'purchase_ok': False,
                'list_price': (tmpl.default_hours or 0.0) * (self.hourly_rate or 0.0),
                'default_code': 'TASK-%d' % tmpl.id,
                'description_sale': _("%(hours)s default hours (%(phase)s)",
                                       hours=tmpl.default_hours,
                                       phase=phase_labels.get(tmpl.phase, tmpl.phase)),
            }
            if tmpl.product_id:
                tmpl.product_id.write(vals)
                product_ids.append(tmpl.product_id.id)
            else:
                product = self.env['product.product'].create(vals)
                tmpl.product_id = product.id
                product_ids.append(product.id)
        return {
            'type': 'ir.actions.act_window',
            'name': _('Products'),
            'res_model': 'product.product',
            'view_mode': 'list,form',
            'domain': [('id', 'in', product_ids)],
        }

    def action_remove_products(self):
        """Removes what it safely can, one product at a time (each in its own savepoint) —
        a product already referenced by a sale/invoice line can't be deleted (a raw DB
        foreign-key error, not a clean Odoo one, since product.product doesn't guard against
        this itself), and one such product shouldn't block removing all the others."""
        self.ensure_one()
        templates = self.env['partner.project.template.task'].search([('product_id', '!=', False)])
        if not templates:
            raise UserError(_("No imported products found — nothing to remove."))
        removed = 0
        blocked = []
        for tmpl in templates:
            product = tmpl.product_id
            try:
                with self.env.cr.savepoint():
                    product.unlink()
                tmpl.product_id = False
                removed += 1
            except Exception:
                blocked.append(product.display_name)
        message = _("%(removed)s product(s) removed.", removed=removed)
        if blocked:
            message += " " + _(
                "%(count)s couldn't be removed because they're already used elsewhere "
                "(e.g. a sale order or invoice): %(names)s",
                count=len(blocked), names=', '.join(blocked))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Remove Imported Products'),
                'message': message,
                'type': 'warning' if blocked else 'success',
                'sticky': bool(blocked),
            },
        }
