from odoo import models, fields, api
from odoo.exceptions import ValidationError


class HrAllowance(models.Model):
    _name = 'hr.allowance'
    _description = 'Employee Allowance'

    name = fields.Char(string='Allowance Name', required=True)
    description = fields.Text(string='Description')
    code = fields.Char(string='Code', required=True)
    amount = fields.Float(string='Default Amount')

    allowance_type_id = fields.Many2one(
        'hr.allowance.type',
        string="Type",
        required=True,
        help="Select or create a type for this allowance."
    )

    active = fields.Boolean(default=True)
    display_type = fields.Char(string='Display Type', compute='_compute_display_type', store=False)

    _sql_constraints = [
        ('code_unique', 'unique(code)', 'Each allowance must have a unique code.')
    ]

    # ------------------------------
    # AUTO-SUGGEST NEXT AVAILABLE CODE
    # ------------------------------
    @api.onchange('allowance_type_id')
    def _onchange_allowance_type_id(self):
        """Auto-suggest the next available code based on selected type"""
        if not self.allowance_type_id:
            return

        base_code = int(self.allowance_type_id.type_code)
        start = base_code + 1
        end = base_code + 99

        # Find all existing codes within this range
        existing_codes = (
            self.env['hr.allowance']
            .sudo()
            .search([('code', '>=', str(start)), ('code', '<=', str(end))])
            .mapped('code')
        )
        numeric_codes = sorted([int(c) for c in existing_codes if c.isdigit()])
        # Find the first available code in the range
        next_code = None
        for candidate in range(start, end + 1):
            if candidate not in numeric_codes:
                next_code = candidate
                break
        # Default fallback if all taken
        if not next_code:
            self.code = ''
            return {
                'warning': {
                    'title': "Code Range Full",
                    'message': f"All codes between {start}-{end} are already used for this type."
                }
            }
        self.code = str(next_code)

        # Suggest code or show warning
        if next_code <= end:
            self.code = str(next_code)
        else:
            self.code = ''
            return {
                'warning': {
                    'title': "Code Range Full",
                    'message': f"All codes between {start}-{end} are already used for this type."
                }
            }

    # ------------------------------
    # VALIDATIONS
    # ------------------------------
    @api.constrains('code', 'allowance_type_id')
    def _check_code_constraints(self):
        """Ensure code is unique, valid, and not conflicting with type codes"""
        for rec in self:
            if not rec.allowance_type_id or not rec.code:
                continue

            # 1️⃣ Prevent using same code as Allowance Type
            type_code = int(rec.allowance_type_id.type_code)
            if rec.code == str(type_code):
                raise ValidationError(
                    f"Code {rec.code} is reserved for Allowance Type '{rec.allowance_type_id.name}'."
                )

            # 2️⃣ Must stay within range
            start = type_code + 1
            end = type_code + 99
            try:
                c_int = int(rec.code)
            except ValueError:
                raise ValidationError("Allowance code must be a number (e.g. 301, 302, 401...).")

            if c_int < start or c_int > end:
                raise ValidationError(
                    f"Code {rec.code} must be within range {start}-{end} for type '{rec.allowance_type_id.name}'."
                )

    # ------------------------------
    # DISPLAY TYPE (for reference in views)
    # ------------------------------
    @api.depends('allowance_type_id')
    def _compute_display_type(self):
        for rec in self:
            rec.display_type = rec.allowance_type_id.name if rec.allowance_type_id else ''

    # ------------------------------
    # AUTO-CREATE SALARY RULE ON CREATION
    # ------------------------------
    @api.model
    def create(self, vals):
        record = super().create(vals)

        structure = self.env['hr.payroll.structure'].search([], limit=1)
        if structure:
            category = self.env.ref('hr_payroll.ALW', raise_if_not_found=False)
            self.env['hr.salary.rule'].create({
                'name': record.name,
                'code': f"ALW_{record.code or record.id}",
                'category_id': category.id if category else False,
                'sequence': 100 + record.id,
                'amount_select': 'code',
                'amount_python_compute': f"result = contract.get_allowances_by_code('{record.code}')",
                'struct_id': structure.id,
                'active': True,
            })
        return record