from odoo import models, api

class HrPayslip(models.Model):
    _inherit = 'hr.payslip'

    @api.model
    def get_inputs(self, contracts, date_from, date_to):
        """Inject contract allowances into the payslip computation."""
        res = super(HrPayslip, self).get_inputs(contracts, date_from, date_to)
        for contract in contracts:
            for allowance in contract.allowance_ids:
                res.append({
                    'name': allowance.allowance_id.name,
                    'code': allowance.code,
                    'amount': allowance.amount,
                    'contract_id': contract.id,
                })
        return res